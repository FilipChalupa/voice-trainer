import { describe, expect, it } from "vitest";
import { sessionStats } from "../components/SessionStats";
import type { Recording } from "../api";

const minutes = { min: 5, recommended: 30, target: 60 };
const now = new Date("2026-09-30T12:00:00Z").getTime();

function rec(minutesAgo: number, duration = 6): Recording {
  return { id: `r${minutesAgo}`, text: "x", prompt_id: null, created: new Date(now - minutesAgo * 60000).toISOString(), duration, url: "", peaks: [], reviewed: false, verify: null, source: null, quality: { issues: [] } };
}

describe("sessionStats", () => {
  it("is empty without recordings from today", () => {
    expect(sessionStats([rec(60 * 30)], minutes, 3, now)).toBeNull();
  });

  it("counts today's takes and projects the next goal from the recent pace", () => {
    const takes = [rec(12), rec(9), rec(6), rec(3), rec(0)]; // one 6 s take every 3 minutes
    const s = sessionStats(takes, minutes, 0.5, now)!;
    expect(s.count).toBe(5);
    expect(s.minutes).toBeCloseTo(0.5, 5);
    expect(s.perHour).toBe(25); // 5 takes over 12 minutes
    expect(s.goal).toBe(5);
    // 2.5 minutes of speech per hour, 4.5 minutes to go -> 108 minutes
    expect(s.toGoal).toBe(108);
  });

  it("gives no pace with fewer than three recent takes", () => {
    const s = sessionStats([rec(1)], minutes, 40, now)!;
    expect(s.perHour).toBe(0);
    expect(s.goal).toBe(60);
    expect(s.toGoal).toBeNull();
  });
});
