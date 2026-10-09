/**
 * Where a map is drawn: a PDF page as vectors, or a canvas as pixels. Both are addressed in
 * millimetres of paper, x to the right and y down, so one renderer (isom.ts) draws either.
 *
 * Paths are built up and then painted once, which is what keeps a page of a hundred thousand
 * features small and quick: a whole style layer is one path and one paint operation. Areas are
 * filled with the nonzero rule, which joins the overlapping copies of an area the tiles carry in
 * their buffers into one, and still leaves the holes open: vector tiles wind holes the other way.
 */

import type {jsPDF} from 'jspdf';
import {GState} from 'jspdf';

export interface Stroke {
  /** `#rrggbb`. */
  color: string;
  opacity: number;
  /** Millimetres. */
  width: number;
  /** Dash and gap lengths in millimetres; none for a solid line. */
  dash?: number[];
  cap: 'butt' | 'round' | 'square';
  join: 'miter' | 'round' | 'bevel';
}

export interface Surface {
  moveTo(x: number, y: number): void;
  lineTo(x: number, y: number): void;
  closePath(): void;
  /** A closed circle as a subpath of its own. */
  circle(x: number, y: number, r: number): void;
  /** Fills the current path, nonzero, and ends it. */
  fill(color: string, opacity: number): void;
  /** Strokes the current path and ends it. */
  stroke(stroke: Stroke): void;
  /** Intersects the clip with the current path, nonzero, and ends it. Undone by restore(). */
  clip(): void;
  save(): void;
  restore(): void;
}

/** A Bézier circle's control point distance, as a fraction of the radius. */
const KAPPA = 0.5522847498;

/** A PDF page, in jsPDF's millimetre units with the origin top left. */
export class PdfSurface implements Surface {
  constructor(private readonly pdf: jsPDF) {}

  moveTo(x: number, y: number): void {
    this.pdf.moveTo(x, y);
  }

  lineTo(x: number, y: number): void {
    this.pdf.lineTo(x, y);
  }

  closePath(): void {
    this.pdf.close();
  }

  circle(x: number, y: number, r: number): void {
    const k = r * KAPPA;
    this.pdf.moveTo(x + r, y);
    this.pdf.curveTo(x + r, y + k, x + k, y + r, x, y + r);
    this.pdf.curveTo(x - k, y + r, x - r, y + k, x - r, y);
    this.pdf.curveTo(x - r, y - k, x - k, y - r, x, y - r);
    this.pdf.curveTo(x + k, y - r, x + r, y - k, x + r, y);
    this.pdf.close();
  }

  fill(color: string, opacity: number): void {
    this.withOpacity(opacity, () => {
      this.pdf.setFillColor(color);
      this.pdf.fill();
    });
  }

  stroke({color, opacity, width, dash, cap, join}: Stroke): void {
    this.withOpacity(opacity, () => {
      this.pdf.setDrawColor(color);
      this.pdf.setLineWidth(width);
      this.pdf.setLineDashPattern(dash ?? [], 0);
      this.pdf.setLineCap(cap);
      this.pdf.setLineJoin(join);
      this.pdf.stroke();
    });
  }

  clip(): void {
    this.pdf.clip();
    this.pdf.discardPath();
  }

  save(): void {
    this.pdf.saveGraphicsState();
  }

  restore(): void {
    this.pdf.restoreGraphicsState();
  }

  /**
   * Transparency is a graphics state of its own, so it is set inside a save/restore pair: jsPDF
   * forgets the state it set at a restore, and would otherwise skip setting it again.
   */
  private withOpacity(opacity: number, paint: () => void): void {
    if (opacity >= 1) {
      paint();
      return;
    }
    this.pdf.saveGraphicsState();
    this.pdf.setGState(new GState({opacity, 'stroke-opacity': opacity}));
    paint();
    this.pdf.restoreGraphicsState();
  }
}

/**
 * A canvas, drawn at `pixelsPerMm`. The 2D context is left transformed to millimetres, so the
 * canvas can be drawn on in paper units afterwards too.
 */
export class CanvasSurface implements Surface {
  private path = new Path2D();

  constructor(
    private readonly context: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D,
    pixelsPerMm: number,
  ) {
    context.setTransform(pixelsPerMm, 0, 0, pixelsPerMm, 0, 0);
  }

  moveTo(x: number, y: number): void {
    this.path.moveTo(x, y);
  }

  lineTo(x: number, y: number): void {
    this.path.lineTo(x, y);
  }

  closePath(): void {
    this.path.closePath();
  }

  circle(x: number, y: number, r: number): void {
    this.path.moveTo(x + r, y);
    this.path.arc(x, y, r, 0, 2 * Math.PI);
    this.path.closePath();
  }

  fill(color: string, opacity: number): void {
    this.context.globalAlpha = opacity;
    this.context.fillStyle = color;
    this.context.fill(this.path, 'nonzero');
    this.end();
  }

  stroke({color, opacity, width, dash, cap, join}: Stroke): void {
    this.context.globalAlpha = opacity;
    this.context.strokeStyle = color;
    this.context.lineWidth = width;
    this.context.setLineDash(dash ?? []);
    this.context.lineCap = cap;
    this.context.lineJoin = join;
    this.context.stroke(this.path);
    this.end();
  }

  clip(): void {
    this.context.clip(this.path, 'nonzero');
    this.end();
  }

  save(): void {
    this.context.save();
  }

  restore(): void {
    this.context.restore();
  }

  private end(): void {
    this.context.globalAlpha = 1;
    this.path = new Path2D();
  }
}
