This is a semi-automated tool to fix broken stop signs (highway=stop)
and yield signs (highway=give_way) in OpenStreetMap.

To use:

1. Run a query on https://overpass-turbo.eu/ in your desired area like this:
```
[out:xml][timeout:25];
// gather results
(
  // query part for: “highway=stop”
  node["highway"="stop"]["stop"!~".*"]["direction"!~".*"]({{bbox}});
  way(bn)["highway"];
);
// print results
out meta;/*fixed by auto repair*/
>;
out meta qt;/*fixed by auto repair*/
```
2. Load into JOSM
3. Select all and run this command: File > Download along...
4. Save .osm file
5. Run this script on the .osm file. Usage:

```
python fix_stop_signs.py <input.osm> <output.osm>
```

6. Load the output file into JOSM
7. Check the changes and upload

Don't process a huge file because it will take a long time to run.