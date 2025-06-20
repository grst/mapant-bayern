# mapant-bayern

(Currently, this is at PoC stage and restricted to the Allgäu region)


## How to build

### 1. Download karttapullautin

[karttapullautin](https://github.com/karttapullautin/karttapullautin) is a command line program that generates
orienteering maps from LIDAR tiles. Download and extract the latest version. 

### 2. Obtain LIDAR data

Download the respective `*.laz` tiles from [Geoportal Bayern](https://geodaten.bayern.de/opengeodata/index.html). 
The files are available under CC-BY-4.0 License. Place them in the `in` directory of karttapullautin.


### 3. Get OSM data

OSM data is required to show buildings, roads, paths etc. 

 1. Download a region of interest from [Geofabrik](https://download.geofabrik.de/europe/germany/bayern.html) in `osm.pbf` format.
 2. Reproject to the UTM32 coordinate system and convert to shape files that `karttapullautin` can work with:

    ```bash
    ogr2ogr --config OSM_USE_CUSTOM_INDEXING NO -skipfailures -f "ESRI Shapefile" output_shapes schwaben-latest.osm.pbf -overwrite -t_srs EPSG:25832
    zip -r -j map.shp.zip output_shapes/*
    ```

### 4. Run karttapullautin

Copy `pullauta.ini` from this repo into the karttapullautin directory. 
Maybe adjust some settings (e.g. number of threads). 

The changes from the "default" `ini` file are:
 * enable batch mode and parallel processing
 * use OSM as vector source. 

Simply invoke

```bash

./pullauta
```

in the karttapullautin directory. 

### 5. Run karttapullautin2tiles

[karttapullautin2tiles](https://github.com/grst/karttapullautin2tiles) is a command line program designed to 
take the output of karttapullautin and generate pyramidial tiles that use the web marcator standard. 

```bash
k2t list-tiles --zoom 11 --proj EPSG:25832 /scratch/karttapullautin/allgaeu/out | \
    parallel --pipe -j 4 --block 1 k2t make-tiles --proj EPSG:25832 /scratch/karttapullautin/allgaeu/out /scratch/karttapullautin/allgaeu/tiles2
```

### 6. Deploy

Copy over the tiles to this repository. Place `11`, `12`, ... `17` directly in the repository root. 
Then deploy the site using netlify

```bash
# for preview
netlify deploy

# for production
netlify deploy --prod
```