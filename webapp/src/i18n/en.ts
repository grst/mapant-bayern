export const en = {
  'title.map': 'Mapant Bayern – automatically generated orienteering map',
  'title.about': 'About – Mapant Bayern',

  'nav.menu': 'Menu',
  'nav.close': 'Close menu',
  'nav.about': 'About',
  'nav.source': 'Source on GitHub',
  'nav.otherMaps': 'Other mapant maps',
  'nav.map': 'Map',
  'nav.language': 'Language',

  'hint.zoomIn': 'Zoom in to view the orienteering map',

  'layers.title': 'Layers',
  'layers.toggle': 'Layers',
  'layers.hillshade': 'Hill shading',
  'layers.places': 'Town names',
  'layers.grid': 'Tile grid',

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

  'share.title': 'Copy link to this view',
  'share.copied': 'Link copied to clipboard',
  'share.failed': 'Could not copy the link – please copy it from the address bar',

  'ol.zoomIn': 'Zoom in',
  'ol.zoomOut': 'Zoom out',
  'ol.fullscreen': 'Toggle full screen',

  'footer.madeWith':
    'Made with <a href="https://github.com/karttapullautin/karttapullautin" target="_blank" rel="noopener">karttapullautin</a> and <a href="https://github.com/grst/mapant-nf" target="_blank" rel="noopener">mapant-nf</a>',
  'footer.impressum': 'Impressum',

  'about.back': 'Back to the map',
} as const;

export type Key = keyof typeof en;
