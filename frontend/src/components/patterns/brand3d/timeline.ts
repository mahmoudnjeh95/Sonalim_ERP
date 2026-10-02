/**
 * The welcome intro's choreography and the camera, as pure functions of time:
 * the skill's rule that every frame is a function of t, nothing carried from
 * one frame to the next. Beats from the spec, §2.
 */
import { fitDistance } from "./framing";
import { brandEase, cssEase, easeInOut, lerp, progress, type Vec3 } from "./math";

/** Beat times in seconds from the intro's first rendered frame. */
export const INTRO = {
  semolinaEnd: 1.2,
  pastaStart: 1.2,
  pastaEnd: 2.4,
  orbitStart: 1.8,
  orbitLength: 1.2,
  ringStart: 2.4,
  ringEnd: 3.1,
  glyphStart: 2.8,
  glyphEnd: 3.3,
  wordmarkIn: 3.0,
  handoff: 3.6,
  end: 4.0,
  /** How long a skip takes to fast-forward to the handoff. */
  skip: 0.3,
} as const;

export interface IntroState {
  /** 0..1: the semolina stream flowing in from the depth. */
  stream: number;
  /** 0..1: grains condensing into pasta (each grain staggers inside this, motion.ts). */
  condense: number;
  /** 0..1: pasta tumbling out from where it formed to its track. */
  orbit: number;
  /** 0..1: opacity of the HTML wordmark and tagline. */
  wordmark: number;
  /** 0..1: camera pull-back and the logo's flight to its login slot. */
  handoff: number;
}

export function introState(t: number): IntroState {
  return {
    stream: progress(t, 0, INTRO.semolinaEnd),
    condense: progress(t, INTRO.pastaStart, INTRO.pastaEnd - INTRO.pastaStart),
    orbit: brandEase(progress(t, INTRO.orbitStart, INTRO.orbitLength)),
    wordmark: brandEase(progress(t, INTRO.wordmarkIn, 0.3)) * (1 - progress(t, INTRO.handoff, 0.2)),
    handoff: easeInOut(progress(t, INTRO.handoff, INTRO.end - INTRO.handoff)),
  };
}

export interface LogoState {
  /** 0..1: how much of the ring is drawn, clockwise from the top. */
  ring: number;
  /** 0..1: the wheat glyph rising into the ring. */
  glyph: number;
  /** 0..1: the bloom flash when the ring closes. */
  flash: number;
}

/**
 * The mark's build. During the intro it follows the intro's beats. On a login
 * reached without the intro it plays logo-mark.svg's own CSS build, `build`
 * seconds after the scene appeared (ring 1.6 s from 0.1 s, glyph 0.6 s from
 * 0.5 s, CSS `ease`); Infinity shows the finished mark.
 */
export function logoState(intro: number | null, build: number): LogoState {
  if (intro !== null) {
    const ring = cssEase(progress(intro, INTRO.ringStart, INTRO.ringEnd - INTRO.ringStart));
    const glyph = brandEase(progress(intro, INTRO.glyphStart, INTRO.glyphEnd - INTRO.glyphStart));
    const flash = intro < INTRO.ringEnd ? progress(intro, INTRO.ringEnd - 0.1, 0.1) : 1 - progress(intro, INTRO.ringEnd, 0.35);
    return { ring, glyph, flash };
  }
  return { ring: cssEase(progress(build, 0.1, 1.6)), glyph: cssEase(progress(build, 0.5, 0.6)), flash: 0 };
}

/**
 * Intro time after a skip: from `skippedAt` the clock fast-forwards to the
 * handoff pose in INTRO.skip seconds, then runs on at normal speed. A skip at
 * or after the handoff changes nothing. `since` is real seconds since the skip.
 */
export function skipTime(skippedAt: number, since: number): number {
  if (skippedAt >= INTRO.handoff) return skippedAt + since;
  if (since >= INTRO.skip) return INTRO.handoff + (since - INTRO.skip);
  return lerp(skippedAt, INTRO.handoff, easeInOut(since / INTRO.skip));
}

export const FOV = 35;
/** World radius the intro keeps on the short axis: the logo (radius 0.88) fills 40 % of it. */
export const INTRO_FIT = 2.2;
/** World radius the login keeps on the short axis: wider, so the pasta drifts around the card. */
export const LOGIN_FIT = 3.4;

/** Orbit camera: angles in degrees around `target`. */
export interface CameraPose {
  radius: number;
  azimuth: number;
  elevation: number;
  target: Vec3;
}

function loginPose(time: number, aspect: number): CameraPose {
  return {
    radius: fitDistance(LOGIN_FIT, FOV, aspect),
    azimuth: 4 * Math.sin(time * 0.05),
    elevation: 4 + 1.5 * Math.sin(time * 0.037),
    target: [0, 0, -1],
  };
}

function introPose(t: number, aspect: number): CameraPose {
  // Starts close in the grains and settles back onto the logo by the end of the pasta beat.
  const settle = brandEase(progress(t, 0, INTRO.pastaEnd));
  const drift = progress(t, 0, INTRO.handoff);
  return {
    radius: fitDistance(INTRO_FIT, FOV, aspect) * lerp(0.75, 1, settle),
    azimuth: lerp(-18, -6, drift),
    elevation: lerp(8, 3, drift),
    target: [0, 0, 0],
  };
}

/** The camera at intro time `intro` (null after the intro) and stage time `time`. */
export function cameraPose(intro: number | null, time: number, aspect: number): CameraPose {
  const login = loginPose(time, aspect);
  if (intro === null) return login;
  const u = introState(intro).handoff;
  if (u >= 1) return login;
  const from = introPose(Math.min(intro, INTRO.handoff), aspect);
  return {
    radius: lerp(from.radius, login.radius, u),
    azimuth: lerp(from.azimuth, login.azimuth, u),
    elevation: lerp(from.elevation, login.elevation, u),
    target: [lerp(from.target[0], login.target[0], u), lerp(from.target[1], login.target[1], u), lerp(from.target[2], login.target[2], u)],
  };
}

/** Pointer parallax: up to 2.5° sideways and 2° vertically (pointer in -1..1). */
export function withPointer(pose: CameraPose, pointer: { x: number; y: number }): CameraPose {
  return { ...pose, azimuth: pose.azimuth + pointer.x * 2.5, elevation: pose.elevation - pointer.y * 2 };
}

export function cameraPosition(pose: CameraPose): Vec3 {
  const a = (pose.azimuth * Math.PI) / 180;
  const e = (pose.elevation * Math.PI) / 180;
  const [tx, ty, tz] = pose.target;
  return [tx + pose.radius * Math.cos(e) * Math.sin(a), ty + pose.radius * Math.sin(e), tz + pose.radius * Math.cos(e) * Math.cos(a)];
}
