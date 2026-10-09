export const en = {
  'title.map': 'Mapant Germany – automatically generated orienteering map',
  'title.about': 'About – Mapant Germany',

  'nav.menu': 'Menu',
  'nav.close': 'Close menu',
  'nav.about': 'About',
  'nav.source': 'Source on GitHub',
  'nav.otherMaps': 'Other mapant maps',
  'nav.map': 'Map',
  'nav.language': 'Language',

  'hint.zoomIn': 'Zoom in to view the orienteering map',

  'status.rendered': 'Mapant rendered',
  'status.free': 'LiDAR freely available',
  'status.fee': 'LiDAR against a fee',
  'status.none': 'No LiDAR available',

  'layers.title': 'Layers',
  'layers.toggle': 'Layers',
  'layers.hillshade': 'Hill shading',
  'layers.places': 'Town names',
  'layers.private': 'Private property',
  'layers.cliffs': 'Cliffs',

  'draw.line': 'Measure distance',
  'draw.polygon': 'Measure area',
  'draw.undo': 'Remove last drawing',
  'draw.clear': 'Remove all drawings',
  'draw.hint': 'Click to add points, double-click to finish',

  'print.toggle': 'Export as PDF',
  'print.title': 'Export as PDF',
  'print.scale': 'Scale',
  'print.orientation': 'Format',
  'print.portrait': 'Portrait',
  'print.landscape': 'Landscape',
  'print.area': 'Covers',
  'print.hint': 'The rectangle shows what will be printed.',
  'print.export': 'Create PDF',
  'print.busy': 'Rendering…',
  'print.ready': 'PDF saved',
  'print.failed': 'The PDF could not be created',

  'ocd.title': 'Export as OCAD file',
  'ocd.hint': 'The rectangle shows what will be exported.',
  'ocd.features': 'Map features',
  'ocd.fromLidar': 'From the LiDAR',
  'ocd.fromOsm': 'From OpenStreetMap',
  'ocd.background': 'Include as background map',
  'ocd.backgroundHint':
    'Drawn into a georeferenced image the OCAD file opens with. Both are saved together in a zip file.',
  'ocd.export': 'Create OCAD file',
  'ocd.busy': 'Converting…',
  'ocd.ready': 'OCAD file saved',
  'ocd.failed': 'The OCAD file could not be created',
  'ocd.empty': 'There is no map data in this area',
  'ocd.note': 'An editable basemap for OCAD or OpenOrienteering Mapper. It needs field work.',

  'group.vegetation': 'Vegetation (yellow, green)',
  'group.contours': 'Contours and form lines',
  'group.landforms': 'Knolls and depressions',
  'group.cliffs': 'Cliffs',
  'group.water': 'Water',
  'group.paths': 'Roads and paths',
  'group.manmade': 'Buildings, railways, fences, power lines',
  'group.private': 'Private property (olive)',

  'share.title': 'Copy link to this view',
  'share.copied': 'Link copied to clipboard',
  'share.failed': 'Could not copy the link – please copy it from the address bar',

  'ol.zoomIn': 'Zoom in',
  'ol.zoomOut': 'Zoom out',
  'ol.fullscreen': 'Toggle full screen',

  'footer.madeWith':
    'Made with <a href="https://github.com/karttapullautin/karttapullautin" target="_blank" rel="noopener">karttapullautin</a> and <a href="https://github.com/grst/mapant-nf" target="_blank" rel="noopener">mapant-nf</a>',
  'footer.impressum': 'Impressum',
  'footer.privacy': 'Privacy policy',

  'about.back': 'Back to the map',
} as const;

export type Key = keyof typeof en;
