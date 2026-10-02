I am building
[mapant-bayern](https://mapant.orienteering-allgaeu.de/#map=12.00/47.56350/10.21420&layers=l&lang=en),
an automatically generated orienteering map from LIDAR data. It was generated
using the mapant-nf pipeline (https://github.com/grst/mapant-nf) which uses
[karttapullautin](github.com/karttapullautin/karttapullautin) for the `.laz` to
map conversion.

The current version of mapant-bayern was generated using the default parameters
of karttapullautin. However, since quality and density of the laserscan data
varies between countries, results can be improved by tuning the parameters.

I want you to optimize these parameters for Bayern with respect to

- undergrowth detection
- detection of vegetation
  - most important is white forest vs. any kind of green forest
  - ideally, green-shades should also be accurately represented (use only 3
    shades of green corresponding to the ISOM levels)
  - you can use more greenshades if it helps, but they shall be mapped to the 3
    isom codes with the `greenshadeisom` parameter.
- detection of yellow vs. white
- detection of cliffs
- detection of dotknolls

There's no need to optimize

- detection of water
- detection of buildings

as these stay deactivated.

## Software versions

You shall test against this PR of karttapullautin:
https://github.com/grst/karttapullautin/pull/3 It has vectorization implemented.
This version is already implemented as a container in this PR of mapant-nf:
https://github.com/grst/mapant-nf/pull/2. For fast iteration, it may, however,
be faster to execute kp/tippecanoe outside of the nextflow pipeline.
Importantly, the vector output is what counts. The new version will use
vectorized tiles exclusively.

## Gold standard reference

You can browse omaps.me for real orienteering maps. Make sure that they have
been last updated around the same time as the corresponding laserscan data (+/-
ca. 2 years).

## Assessment of results

Compare the output of the different features (undergrowth/vegetation/...) for
each parameter visually. Come up with reasonable metrics yourself, but focus on
the pereception by human reading the map.

Results can obviously not expected to be perfect. Several parameter choices may
be pareto-optimal. Please present me with several sets of parameters and show
comparisons between them.

There may also be differences of the density of laserscan data across Bavaria.
Explore that systematically and potentially recommend different parameter sets
for different areas.

## Your task

You can iterate over night on this task. Run everything on this machine. You
have approx. 300GB of disk space on a local nvme device and a 250Mbit internet
connection to pull tiles.

--------------------------------------------------------------------------------

That looks already pretty good! Let's keep improving:

- Keep iterating as long as the results improve
- are there any more maps to consider? E.g. omaps.worldofo.com could be another
  source
- one goal is to optimize towards the real orienteering maps. Another one would
  be to chose params such that LAS1.2 and LAS1.4 regions don't look too
  different. In the first version of the map, there are some obvious borders
  visible in the map, e.g. north of Würzburg:
  https://mapant.orienteering-allgaeu.de/#map=12.23/49.92080/9.94445&layers=l&lang=en.
  Don't overdo this though, alignment with the maps is more important and the
  border issue should anyway improve as a side-effect of optimizing the maps.
  But it could be another metric, and evaluate this in the report.
- Show more comparisons between real and generated maps in the report (not just
  one tile of a few examples). Can also be a separate folder with generated
  images to not blow up the HTML too much.
- Add the corresponding pullauta configs as an additional column in the tile csv
  samplesheet used for the pipeline runs. We'll later adjust mapant-nf to handle
  this, but it's beyond the current scope.
- The report should also be available as HTML offline, not just as an artifact
  on claude.ai.
