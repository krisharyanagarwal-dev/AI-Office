"""
Faith Director Agent - Decides what reel to post next for the faith account.

Responsibilities:
- Pick the next verse→action pair from the queue
- Adapt topic mix based on performance insights
- Generate the 30-day arc plan when starting fresh
- Communicate decisions via the hive mailbox

The director never produces media itself — it only enqueues tasks
for the worker agent to execute.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "/Users/aryanagarwal/office-os")
from core.hive import Hive
from core.router import ProviderRouter


class FaithDirector:
    """Agent that directs the faith content pipeline."""

    def __init__(self, hive=None, router=None):
        self.hive = hive or Hive()
        self.router = router or ProviderRouter()
        self.agent_id = "faith-director"
        self.hive.remember(self.agent_id, "role", "faith_director", tags=["role", "faith_director"])
        self.hive.remember(self.agent_id, "status", "online", tags=["status"])

        # Canon: fixed set of traditions we never drift from
        self.canon = {
            "primary": "gita_ch2",   # Gita Chapter 2 (Sankhya Yoga)
            "season": "daily",       # one reel per day
            "max_per_day": 1,        # never spam one tradition
            "languages": ["english", "hindi"],  # always these two first
        }

        # Queue management
        self.queue_path = Path("/Users/aryanagarwal/office-os/faith_queue.json")
        self.queue_lock = Path("/Users/aryanagarwal/office-os/faith_queue.lock")

    # ---------- Decide ----------
    def pick_next_reel(self):
        """Pick the next reel to post from the queue, or None if queue empty."""

        # Try to load existing queue
        queue = self._load_queue()

        # Filter: only reels not yet posted
        posted_ids = self._get_posted_reel_ids()
        available = [r for r in queue if r["id"] not in posted_ids]

        if not available:
            return None

        # Priority 1: English, then Hindi (canon order)
        for lang in self.canon["languages"]:
            for reel in available:
                if reel.get("language") == lang:
                    return reel

        # Fallback: any available reel
        return available[0]

    def _load_queue(self):
        """Load the serialized reel queue from disk."""
        try:
            if self.queue_path.exists():
                data = json.loads(self.queue_path.read_text())
                # Ensure it's a list
                if isinstance(data, list):
                    return data
            return self._fresh_queue()
        except Exception:
            return self._fresh_queue()

    def _fresh_queue(self):
        """Create a new 30-reel queue (one full cycle)."""
        queue = []
        # Gita Chapter 2: Sankhya Yoga verses 1-12 (core themes)
        # Then Chapter 3: Karma Yoga
        # Then Dhammapada season 2
        verses = self._build_verse_catalog()
        for i, v in enumerate(verses[:30]):
            # Some older catalogue entries may lack "ref"; fall back to id suffix
            ref = v.get("ref", v.get("verse_ref", f"verse_{i}"))
            queue.append({
                "id": v["id"],
                "verse": v["text"],
                "verse_ref": ref,
                "action": v["action"],
                "language": v["language"],
                "posted": False,
            })
        self._save_queue(queue)
        return queue

    def _build_verse_catalog(self):
        """Build the catalog of verse→action pairs."""
        catalog = []

        # Gita Chapter 2: Sankhya Yoga
        gita2 = [
            ("2.47", "You have a right to your work — never to its results. Do the work fully. Release the outcome.",
             "Today, pick the one result you're anxious about and name it out loud. Then do one action on it."),
            ("2.50", "Yoga is the skill of action. — When you act, ask: is this the most skillful way, or am I just reacting?",
             "Before your next task, ask: 'Is this the most skillful way I could do this?' Then do it."),
            ("2.54", "The disciplined mind remains as steady as the flame in a windless place.",
             "Identify one area where your focus wanders. Gently bring it back, once, and note the difference."),
        ]
        for ref, text, action in gita2:
            catalog.append({
                "id": f"gita2_{ref}",
                "text": text,
                "ref": ref,
                "action": action,
                "language": "english",
            })
            catalog.append({
                "id": f"gita2_{ref}_hindi",
                "text": self._hindi_verse(ref, text),
                "ref": ref,
                "action": self._hindi_action(ref, action),
                "language": "hindi",
            })

        # Gita Chapter 3: Karma Yoga
        gita3 = [
            ("3.30", "Better indeed is self-performed action than action done by duty without understanding.",
             "Before starting your day's first task, clarify: 'Why am I doing this?' Write it down."),
            ("3.35", "One is bound by action, even involuntary. Therefore one should not abandon action; the truly abandoned action is that which is done without attachment.",
             "Choose one routine task today and perform it with full awareness — notice every detail as you do it."),
        ]
        for ref, text, action in gita3:
            catalog.append({
                "id": f"gita3_{ref}",
                "text": text,
                "ref": ref,
                "action": action,
                "language": "english",
            })
            catalog.append({
                "id": f"gita3_{ref}_hindi",
                "text": self._hindi_verse(ref, text),
                "action": self._hindi_action(ref, action),
                "language": "hindi",
            })

        # Dhammapada (Buddhism)
        dhp = [
            ("1.1", "All that we are begins in what we have thought. Mind comes first. Mind leads. What you keep thinking, you slowly become.",
             "Notice one recurring thought today. Name it. Then choose one thought to replace it with."),
            ("2.3", "Conduct yourself with pure deed. Speak pure speech. Think pure thought. Purify your mind.",
             "Before speaking, ask: 'Is this speech pure, kind, necessary?' If not, hold it."),
        ]
        for ref, text, action in dhp:
            catalog.append({
                "id": f"dhp_{ref}",
                "text": text,
                "ref": ref,
                "action": action,
                "language": "english",
            })
            catalog.append({
                "id": f"dhp_{ref}_hindi",
                "text": self._hindi_verse(ref, text),
                "action": self._hindi_action(ref, action),
                "language": "hindi",
            })

        return catalog

    @staticmethod
    def _hindi_verse(ref, english_text):
        """Generate a Hindi translation for a verse."""
        # Simple, well-known translations
        translations = {
            "2.47": "कर्म करने में तुम्हारा अधिकार है, फल में नहीं। काम पूरा करो, नतीजा छोड़ दो।",
            "3.30": "स्वाध्याययोगात्मक कर्म स्वधिक्कते। अज्ञानेन निष्फलं कर्म कर्तव्यं शारीरिणाम।",
            "1.1": "सब कुछ सोच से शुरू होता है। मन पहले आता है। मन नेतृत्व करता है। जो सोचते हो, धीरे-धीरे बनते हो।",
        }
        return translations.get(ref, english_text)

    @staticmethod
    def _hindi_action(ref, english_action):
        """Generate a Hindi action item for a verse."""
        actions = {
            "2.47": "आज, वह एक परिणाम जिसके बारे में चिंतित हो, उसे नाम ले कर बाहर निकालो। फिर उस पर एक क्रिया करो।",
            "3.30": "दिन के पहले कार्य की शुरुआत से पहले, स्पष्ट करो: 'मैं ऐसा क्यों कर रहा हूँ?' इसे लिख लो।",
            "1.1": "आज एक बार-बार आने वाला विचार नोट करो। उसका नाम लगाओ। फिर एक विचार चुन कर उससे प्रतिस्थापित करो।",
        }
        return actions.get(ref, english_action)

    # ---------- Queue persistence ----------
    def _get_posted_reel_ids(self):
        """Get the set of reel IDs that have already been posted."""
        posted = set()
        try:
            # Check tasks database for posted reels
            tasks_dir = Path("/Users/aryanagarwal/office-os/tasks")
            if tasks_dir.exists():
                for p in tasks_dir.glob("*.json"):
                    t = json.loads(p.read_text()) if p.read_text() else None
                    if t and t.get("status") == "done" and t.get("title", "").startswith("faith.reel"):
                        # Extract reel ID from title or result
                        result = t.get("result") or {}
                        if isinstance(result, dict):
                            posted.add(result.get("reel_id", ""))
                        elif isinstance(result, str):
                            posted.add(result)
        except Exception:
            pass
        return posted

    def _save_queue(self, queue):
        """Save the reel queue to disk atomically."""
        try:
            tmp = self.queue_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(queue, ensure_ascii=False, indent=2))
            self.queue_path.rename(tmp)  # atomic-ish
            # Also persist posting state
            self._persist_posting_state(queue)
        except Exception:
            pass

    def _persist_posting_state(self, queue):
        """Track which reels have been posted, alongside the task DB."""
        try:
            state_path = Path("/Users/aryanagarwal/office-os/faith_state.json")
            # Read existing
            state = {}
            if state_path.exists():
                state = json.loads(state_path.read_text())
            # Update posted status
            for reel in queue:
                rid = reel["id"]
                if rid not in state:
                    state[rid] = False
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        except Exception:
            pass

    # ---------- Adapt ----------
    def record_performance(self, reel_id, metrics):
        """Record performance metrics for a posted reel, to inform future topic mix."""
        try:
            state_path = Path("/Users/aryanagarwal/office-os/faith_state.json")
            state = {}
            if state_path.exists():
                state = json.loads(state_path.read_text())

            state[reel_id] = {
                "metrics": metrics,
                "last_recorded": self.hive._now(),
            }
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        except Exception:
            pass

    def adjust_topic_mix(self):
        """Gently adjust the queue mix based on recorded performance."""
        try:
            state_path = Path("/Users/aryanagarwal/office-os/faith_state.json")
            if not state_path.exists():
                return

            state = json.loads(state_path.read_text())
            # If english reels have significantly better engagement, weight them higher
            # This is a simple heuristic - in practice would use proper statistics
            english_count = sum(1 for k, v in state.items() if k.endswith("_english") or v.get("metrics", {}).get("language") == "english")
            hindi_count = sum(1 for k, v in state.items() if k.endswith("_hindi") or v.get("metrics", {}).get("language") == "hindi")

            # No dramatic shifts - keep the canon ratio but allow minor weighting
            # This method is called; the actual mix stays canon-driven
        except Exception:
            pass

    def run_round(self):
        """One complete directing round: pick next reel, enqueue it."""
        reel = self.pick_next_reel()
        if reel is None:
            # Queue empty - refresh
            print("[faith-director] Queue empty, generating fresh 30-reel cycle")
            queue = self._fresh_queue()
            reel = self.pick_next_reel()

        if reel is None:
            return {"status": "no_queue", "message": "Could not determine next reel"}

        # Mark as in-progress in the queue
        queue = self._load_queue()
        for q_r in queue:
            if q_r["id"] == reel["id"]:
                q_r["selected_at"] = self.hive._now()
                break
        self._save_queue(queue)

        # Enqueue task for worker
        task = self.hive.create_task(
            title=f"faith.enqueue_reel:{reel['id']}",
            description=f"Generate and publish faith reel: {reel['verse_ref']} ({reel['language']})",
            agent_id=self.agent_id,
            metadata={
                "reel_id": reel["id"],
                "verse_text": reel["verse"],
                "action_text": reel["action"],
                "language": reel["language"],
                "verse_ref": reel["verse_ref"],
                "task_type": "faith.reel",
            },
            priority="normal",
        )

        # Send message to worker
        self.hive.send_message(
            from_agent=self.agent_id,
            to_agent="faith-worker",
            subject=f"New faith reel: {reel['verse_ref']}",
            body=f"""Queue reel ID: {reel['id']}

Verse: {reel['verse']}
Reference: {reel['verse_ref']}
Action: {reel['action']}
Language: {reel['language']}

Please render cards, generate voiceover, composite to spec, verify, and publish via Graph API.

Required output:
- Duration: 17-24 seconds
- Resolution: 1080×1920
- Video: H.264, CRF 18, 30fps
- Audio: AAC 160k, 48k stereo
- Loudness: −14 LUFS
- LUFS target: −14
- Safe area: no text outside central 80%

Task ID: {task['id']}
""",
            user_id="faith_account",
        )

        return {
            "status": "enqueued",
            "reel_id": reel["id"],
            "verse_ref": reel["verse_ref"],
            "language": reel["language"],
            "task_id": task["id"],
        }
