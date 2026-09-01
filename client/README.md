# Data Center Site Selection - Client Dashboard

Next.js 14 web application for visualizing PostGIS parcel grid layers, tuning multi-factor suitability scoring weights, and inspecting ML-clustered **Prime Development Zones** for 100+ MW hyperscale facilities.

## Features

- **Interactive PostGIS Map Canvas**: Vector & spatial layer overlays including HIFLD Transmission Lines, Substations, USGS Water Aquifers, FEMA Hazard / Seismic PGA maps, and NOAA Cooling Degree Days.
- **Dynamic Multi-Factor Constraint Sliders**: Adjust Power Proximity, Water Availability, Disaster Risk, and Ambient Cooling weights in real-time with instant client-side recalculation.
- **Ranked Candidate Site List**: Filter and sort 10 km² parcels by composite score and 100+ MW readiness.
- **Prime Development Zone Clusters**: Visual highlight of contiguous parcel clusters identified via Scikit-Learn DBSCAN.
- **Detailed Site Dossier Modal**: Comprehensive physical constraint breakdown for interconnection and chiller feasibility.

## Getting Started

```bash
# Install dependencies
npm install

# Run local development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.
