"""
Unsupervised Geospatial Clustering Model (Scikit-Learn)
------------------------------------------------------
Uses unsupervised machine learning algorithms (DBSCAN & K-Means) to group
high-scoring contiguous 10-square-kilometer parcels into "Prime Development Zones".

Key Concepts for 100+ MW Hyperscale Data Centers:
1. Spatial Adjacency: Multiple adjacent parcels enable multi-building hyperscale campuses (250MW - 1GW+).
2. Interconnection Clustering: Shared high-voltage transmission interconnects and substation substations.
3. Aquifer Basin Sharing: Contiguous water rights and closed-loop cooling infrastructure.
"""

from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon, Point
from shapely.ops import unary_union
from sklearn.cluster import DBSCAN, KMeans
from sklearn.preprocessing import StandardScaler
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clustering_model")


class SiteClusteringModel:
    """Unsupervised clustering engine for geospatial parcel grouping."""

    def __init__(
        self,
        min_composite_score: float = 65.0,
        eps_km: float = 8.5,
        min_samples: int = 2
    ):
        """
        Parameters:
            min_composite_score: Minimum suitability threshold for cluster candidacy.
            eps_km: Maximum distance in kilometers for spatial adjacency (DBSCAN neighborhood).
            min_samples: Minimum contiguous parcels required to form a Prime Zone.
        """
        self.min_composite_score = min_composite_score
        self.eps_km = eps_km
        self.min_samples = min_samples

    def fit_prime_zones_dbscan(
        self,
        grid_gdf: gpd.GeoDataFrame,
        score_column: str = "composite_score"
    ) -> Tuple[gpd.GeoDataFrame, Dict[int, Dict[str, Any]]]:
        """
        Executes spatial DBSCAN clustering using Haversine distance on high-scoring candidate parcels.

        Returns:
            - Enriched GeoDataFrame with `cluster_zone_id`, `cluster_label`, `is_prime_zone`, `megawatt_capacity_estimate`.
            - Cluster summary dictionary with aggregate area, MW capacity, and boundary geometry.
        """
        df = grid_gdf.copy()

        # Initialize defaults
        df["cluster_zone_id"] = -1
        df["cluster_label"] = "Secondary Candidate"
        df["is_prime_zone"] = False
        df["megawatt_capacity_estimate"] = 100

        # Filter candidate parcels exceeding score threshold
        candidate_mask = df[score_column] >= self.min_composite_score
        candidates = df[candidate_mask].copy()

        cluster_summaries: Dict[int, Dict[str, Any]] = {}

        if len(candidates) < self.min_samples:
            logger.warning(f"Only {len(candidates)} candidate parcels found >= {self.min_composite_score}. Lowering threshold to 55.0.")
            candidate_mask = df[score_column] >= 55.0
            candidates = df[candidate_mask].copy()

        if len(candidates) >= self.min_samples:
            # Extract coordinates in radians for Haversine metric (Lat, Lon)
            coords_rad = np.radians(np.vstack([
                candidates["centroid"].apply(lambda p: p.y).values,
                candidates["centroid"].apply(lambda p: p.x).values
            ]).T)

            # Convert eps_km to radians on Earth sphere (R ~ 6371.0 km)
            eps_rad = self.eps_km / 6371.0

            dbscan = DBSCAN(eps=eps_rad, min_samples=self.min_samples, metric="haversine")
            cluster_labels = dbscan.fit_predict(coords_rad)
            candidates["cluster_zone_id"] = cluster_labels

            valid_cluster_ids = [c for c in np.unique(cluster_labels) if c >= 0]
            logger.info(f"DBSCAN identified {len(valid_cluster_ids)} contiguous cluster zones.")

            # Rank clusters by mean composite score
            ranked_clusters = []
            for cid in valid_cluster_ids:
                c_parcels = candidates[candidates["cluster_zone_id"] == cid]
                avg_score = float(c_parcels[score_column].mean())
                ranked_clusters.append((cid, avg_score, len(c_parcels)))

            ranked_clusters.sort(key=lambda x: x[1], reverse=True)

            # Assign zone letters (A, B, C...) and calculate cluster footprints
            for rank_idx, (cid, avg_score, parcel_count) in enumerate(ranked_clusters):
                zone_letter = chr(65 + rank_idx)  # A, B, C...
                total_area_km2 = parcel_count * 10.0
                mw_capacity = int(min(1500, parcel_count * 200))
                zone_label = f"Prime Zone {zone_letter} ({int(total_area_km2)} km² Hyper-Cluster)"

                mask = candidates["cluster_zone_id"] == cid
                candidates.loc[mask, "cluster_label"] = zone_label
                candidates.loc[mask, "is_prime_zone"] = True
                candidates.loc[mask, "megawatt_capacity_estimate"] = mw_capacity

                # Build cluster boundary polygon
                cluster_geoms = candidates.loc[mask, "geometry"].values
                union_geom = unary_union(cluster_geoms)

                cluster_summaries[cid] = {
                    "cluster_zone_id": cid,
                    "zone_letter": zone_letter,
                    "label": zone_label,
                    "parcel_count": parcel_count,
                    "avg_composite_score": round(avg_score, 2),
                    "total_area_sq_km": total_area_km2,
                    "total_mw_capacity": mw_capacity,
                    "boundary_wkt": union_geom.wkt
                }

            # Update master dataframe
            df.update(candidates)

        return df, cluster_summaries

    def fit_multidimensional_kmeans(
        self,
        grid_gdf: gpd.GeoDataFrame,
        n_clusters: int = 4
    ) -> gpd.GeoDataFrame:
        """
        Clustering across physical constraint dimensions:
        [Power Score, Water Score, Risk Score, Climate Score, Longitude, Latitude]
        """
        df = grid_gdf.copy()
        
        feature_matrix = np.column_stack([
            df["power_score"].values,
            df["water_score"].values,
            df["risk_score"].values,
            df["climate_score"].values,
            df["centroid"].apply(lambda p: p.x).values,
            df["centroid"].apply(lambda p: p.y).values
        ])

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(feature_matrix)

        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        df["kmeans_tier_id"] = kmeans.fit_predict(X_scaled)
        
        return df


if __name__ == "__main__":
    from grid_parser import GridParser

    print("=" * 60)
    print("TESTING SCIKIT-LEARN CLUSTERING MODEL LOCALLY")
    print("=" * 60)

    parser = GridParser()
    grid = parser.generate_10km_grid(-77.85, 38.75, -77.25, 39.25, state_code="VA", county_name="Loudoun")
    grid = parser.intersect_hifld_power_grid(grid)
    grid = parser.intersect_water_and_climate(grid)
    grid = parser.intersect_hazard_risk(grid)
    scored = parser.calculate_composite_scores(grid)

    model = SiteClusteringModel(min_composite_score=60.0, eps_km=8.5, min_samples=2)
    clustered, summaries = model.fit_prime_zones_dbscan(scored)

    print(f"\nTotal Parcels Scored: {len(clustered)}")
    print(f"Prime Parcels Found: {len(clustered[clustered['is_prime_zone'] == True])}")
    print(f"Identified {len(summaries)} Prime Development Clusters:\n")

    for cid, s in summaries.items():
        print(f"  ★ {s['label']}:")
        print(f"     - Parcels: {s['parcel_count']} ({s['total_area_sq_km']} km²)")
        print(f"     - Avg Suitability Score: {s['avg_composite_score']}/100")
        print(f"     - Feasible Megawatt Capacity: {s['total_mw_capacity']} MW")

    print("\nTop 5 Individual Parcels:")
    print(clustered[["grid_id", "composite_score", "power_score", "water_score", "cluster_label"]].head())
