# mapant-bayern

## Get OSM data

```
ogr2ogr --config OSM_USE_CUSTOM_INDEXING NO -skipfailures -f "ESRI Shapefile" output_shapes schwaben-latest.osm.pbf -overwrite -t_srs EPSG:25832
zip -r -j map.shp.zip output_shapes/*
```
