# tools — image library pipeline

`build_images.py` turns high-res Audubon plates into panel-ready images and
keeps `wall-node/species_map.json` in sync.

## Where to get the plates (public domain)

Audubon's *Birds of America* (published 1827–1838) is public domain. High-res
sources:

- National Audubon Society gallery — https://www.audubon.org/art/birds-of-america
- Internet Archive scans — https://archive.org/details/AudobonBirdsOfAmerica
- Rawpixel (CC0, cleaned up) — https://www.rawpixel.com/search?path=1522.sub_topic-1814

Download the plates for the species you actually get in your area (BirdNET-Go's
detection list, weighted by your lat/long, is a good shortlist).

## Workflow

1. Drop source images into a folder, e.g. `tools/source_plates/`.
2. Make a `plates.csv` mapping each file to a species:

   ```csv
   source,scientific_name,common_name,output
   plate_102.jpg,Cardinalis cardinalis,Northern Cardinal,northern_cardinal.jpg
   plate_021.jpg,Cyanocitta cristata,Blue Jay,blue_jay.jpg
   ```

   `scientific_name` **must** match what BirdNET-Go emits (that's the lookup
   key). `output` is optional — derived from the common name if blank.

3. Build:

   ```bash
   cd tools
   python build_images.py --src ./source_plates --csv ./plates.csv
   ```

   This writes fitted JPEGs into `wall-node/images/` and updates
   `wall-node/species_map.json`. Re-running merges new entries into the map.

## Notes

- Color dithering to the Spectra-6 palette happens at **display time**
  (`wall-node/renderer.to_panel`), so the library stays full-color and flexible.
- Species with no plate fall back to a caption-only "card" on the panel and are
  logged by the display service — a handy to-do list for extending the library.
