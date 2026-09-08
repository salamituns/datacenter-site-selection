-- The statute and the list of what a roll-back figure leaves out were
-- hardcoded in the estimator, which was only correct while Virginia was
-- the only jurisdiction. Virginia adds a 50% penalty on rezoning within
-- five years; Ohio attaches a lien and has no equivalent penalty. Both
-- now travel with the assumption that priced the figure.
UPDATE public.cost_assumptions
   SET params = params || jsonb_build_object(
         'statute', 'Code of Virginia 58.1-3237',
         'excludes', jsonb_build_array(
            'statutory simple interest',
            '50% penalty where rezoned to a more intensive use within five years'))
 WHERE assumption_key = 'land_use_rollback'
   AND jurisdiction = 'Loudoun County, VA';

UPDATE public.cost_assumptions
   SET params = params || jsonb_build_object(
         'statute', 'Ohio Revised Code 5713.34',
         'excludes', jsonb_build_array(
            'interest and penalties on the recoupment charge',
            'the lien the charge places on the converted land'))
 WHERE assumption_key = 'land_use_rollback'
   AND jurisdiction = 'Franklin County, OH';
