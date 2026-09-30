// Minimal stub replaced by Task 22 (the review panel: header, section grids, sources, flags).
import type { ReviewState, SessionDetail } from "./scanApi";

export function ReviewPanel(props: { session: SessionDetail; review: ReviewState; updateReview: (change: (current: ReviewState) => ReviewState) => void }) {
  void props;
  return null;
}
