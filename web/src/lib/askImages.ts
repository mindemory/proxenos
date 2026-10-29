"use client";

// Screenshots for a question, made small in the browser before they're sent: the longest side at
// most 1600 px, re-encoded as JPEG. That keeps a request to a few hundred KB over a phone's
// connection, and drops whatever metadata the original carried (where a photo was taken, say).

import { ASK_IMAGE_TYPES, ASK_MAX_IMAGE_BYTES, type AskImage } from "./types";

export const LONGEST_SIDE = 1600;
const QUALITY = 0.85;
/** If a picture still comes out too big (a huge one full of noise), try again at these. */
const FALLBACK_QUALITIES = [0.7, 0.55, 0.4];
/** A file bigger than this isn't opened at all. */
const MAX_FILE_BYTES = 50 * 1024 * 1024;

export const IMAGE_ACCEPT = ASK_IMAGE_TYPES.join(",");

/** A screenshot ready to send, and a small picture of it to show. */
export interface Attachment {
  key: string;
  image: AskImage;
  /** A data: URL of the same JPEG, for a thumbnail. */
  preview: string;
}

/** Whether a dropped or pasted file is a kind of picture a question takes. */
export function isAskImage(file: File): boolean {
  return (ASK_IMAGE_TYPES as readonly string[]).includes(file.type);
}

interface Decoded {
  source: CanvasImageSource;
  width: number;
  height: number;
  release: () => void;
}

async function decode(file: Blob): Promise<Decoded> {
  if (typeof createImageBitmap === "function") {
    try {
      // Turned the way its EXIF says, as browsers do by default.
      const bitmap = await createImageBitmap(file);
      return { source: bitmap, width: bitmap.width, height: bitmap.height, release: () => bitmap.close() };
    } catch {
      // Fall through to an <img>, which some browsers read more kinds with.
    }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return { source: img, width: img.naturalWidth, height: img.naturalHeight, release: () => undefined };
  } finally {
    URL.revokeObjectURL(url);
  }
}

function toBlob(canvas: HTMLCanvasElement, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
}

function dataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

let counter = 0;

/** Make one picture small. Throws an Error whose message is for the reader. */
export async function prepareImage(file: File): Promise<Attachment> {
  if (!isAskImage(file)) throw new Error("Only PNG, JPEG or WebP pictures can be added.");
  if (file.size > MAX_FILE_BYTES) throw new Error("That picture is too large to open here.");
  let decoded: Decoded;
  try {
    decoded = await decode(file);
  } catch {
    throw new Error("Couldn't read that picture.");
  }
  try {
    const { width, height } = decoded;
    if (!width || !height) throw new Error("Couldn't read that picture.");
    const scale = Math.min(1, LONGEST_SIDE / Math.max(width, height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Couldn't read that picture.");
    // A JPEG has no transparency: a see-through PNG would turn black.
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(decoded.source, 0, 0, canvas.width, canvas.height);

    for (const quality of [QUALITY, ...FALLBACK_QUALITIES]) {
      const blob = await toBlob(canvas, quality);
      if (!blob) throw new Error("Couldn't read that picture.");
      if (blob.size > ASK_MAX_IMAGE_BYTES) continue;
      const url = await dataUrl(blob);
      return {
        key: `shot-${++counter}`,
        image: { type: "image/jpeg", data: url.slice(url.indexOf(",") + 1) },
        preview: url,
      };
    }
    throw new Error("That picture is too large, even made smaller.");
  } finally {
    decoded.release();
  }
}
