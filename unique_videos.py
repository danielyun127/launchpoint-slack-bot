"""
Counts unique videos for a campaign whose creators cross-post the same video
to several platforms (one video on TikTok + Instagram + YouTube + Facebook
counts once).

Grouping, starting from LaunchPoint's crossPostGroupId:
1. Split repeats: a group sometimes holds the same platform twice (a creator's
   second video, or a re-upload, filed under the same group). Walking the
   group's posts in time order, a post on a platform the current video
   already has starts a new video.
2. Merge split groups: LaunchPoint occasionally files one cross-post under
   two groups. Two videos from the same creator, on non-overlapping
   platforms, first posted within MERGE_WINDOW of each other, are one video.

A video qualifies toward the goal once any of its posts has min_views+ views.
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass

MERGE_WINDOW = datetime.timedelta(minutes=15)


@dataclass
class VideoCounts:
    unique: int      # all unique videos posted
    qualifying: int  # unique videos with a post at min_views+ views


def _split_repeats(group: list) -> list:
    videos = []
    for post in sorted(group, key=lambda p: p.get("uploadedAt") or 0):
        if not videos or post["platform"] in {p["platform"] for p in videos[-1]}:
            videos.append([])
        videos[-1].append(post)
    return videos


def group_videos(posts: list) -> list:
    """Returns one list of posts per unique video."""
    groups = defaultdict(list)
    for p in posts:
        # A post with no group ID is its own video.
        groups[p.get("crossPostGroupId") or p["id"]].append(p)

    videos = [video for group in groups.values() for video in _split_repeats(group)]

    first_post_ms = lambda video: min(p.get("uploadedAt") or 0 for p in video)
    window_ms = MERGE_WINDOW.total_seconds() * 1000
    merged = []
    for video in sorted(videos, key=first_post_ms):
        platforms = {p["platform"] for p in video}
        for other in merged:
            if (
                other[0]["creatorId"] == video[0]["creatorId"]
                and not platforms & {p["platform"] for p in other}
                and abs(first_post_ms(video) - first_post_ms(other)) <= window_ms
            ):
                other.extend(video)
                break
        else:
            merged.append(list(video))
    return merged


def count_videos(posts: list, min_views: int) -> VideoCounts:
    videos = group_videos(posts)
    qualifying = sum(1 for v in videos if any((p.get("views") or 0) >= min_views for p in v))
    return VideoCounts(unique=len(videos), qualifying=qualifying)
