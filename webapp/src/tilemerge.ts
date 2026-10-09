/**
 * Merging vector tiles: one tile on a border between two states' archives, each holding its own
 * side of it (archive.ts).
 *
 * Merging is a rewrite of the protobuf, not a decode into features: each tile's layers are
 * appended to the merged tile's layer of the same name, with the tag indices shifted onto the
 * merged key and value tables. Nothing is re-clipped. The buffers overlap inside the merged tile,
 * where they are drawn twice in the same place.
 */

import {PbfReader, PbfWriter} from 'pbf';

interface MergedLayer {
  version: number;
  keys: string[];
  keyIndex: Map<string, number>;
  /** Value messages kept as their encoded bytes; equal values share an entry. */
  values: Uint8Array[];
  valueIndex: Map<string, number>;
  features: {id?: number; type: number; tags: number[]; geometry: number[]}[];
}

const MOVE_TO = 1;
const LINE_TO = 2;
const CLOSE_PATH = 7;

const zigzag = (n: number) => (n << 1) ^ (n >> 31);
const unzigzag = (n: number) => (n >>> 1) ^ -(n & 1);

/**
 * The geometry command stream with every position scaled and shifted. Positions are deltas from
 * the previous one, so they are made absolute, transformed and made relative again.
 */
function transformGeometry(geometry: number[], scale: number, dx: number, dy: number): number[] {
  const out: number[] = [];
  let x = 0;
  let y = 0;
  let outX = 0;
  let outY = 0;
  for (let i = 0; i < geometry.length; ) {
    const command = geometry[i++];
    const id = command & 0x7;
    const count = command >> 3;
    out.push(command);
    if (id === MOVE_TO || id === LINE_TO) {
      for (let j = 0; j < count; j++) {
        x += unzigzag(geometry[i++]);
        y += unzigzag(geometry[i++]);
        const nextX = Math.round(x * scale + dx);
        const nextY = Math.round(y * scale + dy);
        out.push(zigzag(nextX - outX), zigzag(nextY - outY));
        outX = nextX;
        outY = nextY;
      }
    } else if (id !== CLOSE_PATH) {
      throw new Error(`unknown geometry command ${id}`);
    }
  }
  return out;
}

function valueKey(bytes: Uint8Array): string {
  let key = '';
  for (const byte of bytes) {
    key += String.fromCharCode(byte);
  }
  return key;
}

/** Appends one child tile, whose square is at (column, row) of the merged tile's grid. */
function appendTile(
  layers: Map<string, MergedLayer>,
  data: ArrayBuffer,
  column: number,
  row: number,
  mergedExtent: number,
  span: number,
): void {
  const pbf = new PbfReader(data);
  pbf.readFields((field) => {
    if (field !== 3) {
      return;
    }
    const layer = {
      name: '',
      extent: CHILD_EXTENT,
      version: 2,
      keys: [] as string[],
      values: [] as Uint8Array[],
      features: [] as number[],
    };
    const end = pbf.readVarint() + pbf.pos;
    pbf.readFields(
      (layerField) => {
        if (layerField === 1) layer.name = pbf.readString();
        else if (layerField === 2) {
          layer.features.push(pbf.pos);
          pbf.skip(2);
        } else if (layerField === 3) layer.keys.push(pbf.readString());
        else if (layerField === 4) layer.values.push(pbf.readBytes());
        else if (layerField === 5) layer.extent = pbf.readVarint();
        else if (layerField === 15) layer.version = pbf.readVarint();
      },
      layer,
      end,
    );

    let merged = layers.get(layer.name);
    if (!merged) {
      merged = {
        version: layer.version,
        keys: [],
        keyIndex: new Map(),
        values: [],
        valueIndex: new Map(),
        features: [],
      };
      layers.set(layer.name, merged);
    }
    const keyMap = layer.keys.map((key) => {
      let index = merged.keyIndex.get(key);
      if (index === undefined) {
        index = merged.keys.push(key) - 1;
        merged.keyIndex.set(key, index);
      }
      return index;
    });
    const valueMap = layer.values.map((bytes) => {
      const key = valueKey(bytes);
      let index = merged.valueIndex.get(key);
      if (index === undefined) {
        index = merged.values.push(bytes) - 1;
        merged.valueIndex.set(key, index);
      }
      return index;
    });

    const scale = mergedExtent / span / layer.extent;
    const dx = (column * mergedExtent) / span;
    const dy = (row * mergedExtent) / span;
    const after = pbf.pos;
    for (const start of layer.features) {
      pbf.pos = start;
      const feature = {id: undefined as number | undefined, type: 0, tags: [] as number[], geometry: [] as number[]};
      pbf.readMessage((featureField) => {
        if (featureField === 1) feature.id = pbf.readVarint();
        else if (featureField === 2) pbf.readPackedVarint(feature.tags);
        else if (featureField === 3) feature.type = pbf.readVarint();
        else if (featureField === 4) pbf.readPackedVarint(feature.geometry);
      }, feature);
      merged.features.push({
        id: feature.id,
        type: feature.type,
        tags: feature.tags.map((tag, i) => (i % 2 === 0 ? keyMap[tag] : valueMap[tag])),
        geometry: transformGeometry(feature.geometry, scale, dx, dy),
      });
    }
    pbf.pos = after;
  }, undefined);
}

function encode(layers: Map<string, MergedLayer>, extent: number): ArrayBuffer {
  const pbf = new PbfWriter();
  for (const [name, layer] of layers) {
    pbf.writeMessage(
      3,
      () => {
        pbf.writeVarintField(15, layer.version);
        pbf.writeStringField(1, name);
        for (const feature of layer.features) {
          pbf.writeMessage(
            2,
            () => {
              if (feature.id !== undefined) pbf.writeVarintField(1, feature.id);
              pbf.writePackedVarint(2, feature.tags);
              pbf.writeVarintField(3, feature.type);
              pbf.writePackedVarint(4, feature.geometry);
            },
            undefined,
          );
        }
        for (const key of layer.keys) pbf.writeStringField(3, key);
        for (const value of layer.values) pbf.writeBytesField(4, value);
        pbf.writeVarintField(5, extent);
      },
      undefined,
    );
  }
  const bytes = pbf.finish();
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
}

/** The extent the children are written at: mapant-nf cuts its 512 px tiles at 8192. */
const CHILD_EXTENT = 8192;

/**
 * Several archives' versions of one tile as one: the layers of the same name joined, geometry as
 * it is. That is what a tile on a border between two states' archives needs -- each archive holds
 * its own side, buffer included, exactly as two parents' copies of a tile do in mapant-nf.
 */
export function mergeTiles(tiles: ArrayBuffer[]): ArrayBuffer {
  const layers = new Map<string, MergedLayer>();
  for (const data of tiles) {
    appendTile(layers, data, 0, 0, CHILD_EXTENT, 1);
  }
  return encode(layers, CHILD_EXTENT);
}
