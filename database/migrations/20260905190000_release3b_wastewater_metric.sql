-- ============================================================================
-- Migration: release3b_wastewater_metric
-- Description: Wastewater service companion metrics from the same Loudoun
--   Water service-area boundary (ServiceType WW / Both areas).
--
--   Informational only — wastewater never drives a gate. The provider is
--   recorded (observed) when at least half the parcel lies in a
--   wastewater-servicing area; the overlap share is always recorded
--   (derived). Capacity and connection fees remain diligence items.
-- ============================================================================

INSERT INTO public.metric_definitions (metric_key, label, gate_key, unit, description) VALUES
    ('wastewater_service_provider', 'Wastewater service provider', NULL, NULL,
     'Loudoun Water wastewater-servicing area for the parcel (observed from the utility''s published service-area boundary, ServiceType WW/Both) — informational, not a gate'),
    ('wastewater_service_area_pct', 'Wastewater service-area overlap', NULL, 'percent',
     'Share of the parcel inside Loudoun Water''s published wastewater-servicing boundary (derived) — informational, not a gate')
ON CONFLICT (metric_key) DO NOTHING;
