import test from "node:test";
import assert from "node:assert/strict";
import {
  MEETING_IMAGE_LIMIT,
  meetingImageError,
  meetingImageSelectionError,
} from "../src/meeting-images.js";

test("accepts JPG, PNG and WebP images within the size limit", () => {
  assert.equal(meetingImageError({ type: "image/png", name: "现场.png", size: 10 }), null);
  assert.equal(meetingImageError({ type: "image/jpeg", name: "现场.jpg", size: 10 }), null);
  assert.equal(meetingImageError({ type: "image/webp", name: "现场.webp", size: 10 }), null);
  assert.equal(
    meetingImageError({ type: "", name: "手机照片.JPEG", size: 10 }),
    null,
  );
});

test("rejects non-images, empty files and oversized images", () => {
  assert.match(
    meetingImageError({ type: "application/pdf", name: "会议.pdf", size: 10 }),
    /JPG、PNG 或 WebP/,
  );
  assert.match(
    meetingImageError({ type: "image/png", name: "空.png", size: 0 }),
    /不能为空/,
  );
  assert.match(
    meetingImageError({ type: "image/png", name: "大.png", size: 10 * 1024 * 1024 + 1 }),
    /10 MB/,
  );
});

test("limits the combined existing and newly selected images", () => {
  const image = { type: "image/png", name: "现场.png", size: 10 };
  assert.equal(meetingImageSelectionError([image], MEETING_IMAGE_LIMIT - 1), null);
  assert.match(
    meetingImageSelectionError([image], MEETING_IMAGE_LIMIT),
    new RegExp(String(MEETING_IMAGE_LIMIT)),
  );
});
