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
  'print.exportOcd': 'Create OCAD file',
  'print.ocdBusy': 'Converting…',
  'print.ocdReady': 'OCAD file saved',
  'print.ocdFailed': 'The OCAD file could not be created',
  'print.ocdEmpty': 'There is no map data in this area',
  'print.ocdHint': 'An editable basemap for OCAD or OpenOrienteering Mapper. It needs field work.',

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
