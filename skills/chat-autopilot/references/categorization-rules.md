# Message Categorization Rules

## Priority Signals

### Urgent
- Keywords: "ASAP", "urgent", "blocker", "incident", "down", "broken", "P0", "P1", "production", "outage", "gấp", "khẩn"
- Patterns: ALL CAPS messages, multiple exclamation marks with action words
- Context: messages from managers/leads about deadlines
- Time sensitivity: mentions specific short deadlines ("by EOD", "in 1 hour", "trước 5h")

### Action Needed
- Keywords: "review", "approve", "please", "can you", "could you", "need your", "assigned", "task", "check", "nhờ", "giúp"
- Patterns: questions directed at user, @mentions with requests
- Context: PR review requests, approval workflows, direct questions

### FYI
- Keywords: "FYI", "heads up", "update", "announcement", "note", "reminder", "thông báo"
- Patterns: broadcast messages, no question marks, informational tone
- Context: team updates, meeting notes, status reports, newsletter-style messages

### Social
- Keywords: "thanks", "hi", "hello", "good morning", "congrats", "happy", "cảm ơn", "chào"
- Patterns: emoji-only messages, short greetings, reactions
- Context: casual conversations, celebrations, end-of-thread acknowledgments

## Edge Cases

### Ambiguous Messages
When category is unclear, default to **Action Needed** (safer to surface than to auto-reply).

### Multi-Category Messages
If a message contains both urgent and social signals (e.g., "Hey! The server is down!"), categorize by the highest priority signal → **Urgent**.

### Thread Context
Consider the thread context when categorizing:
- A "thanks" in a thread about an incident → Social (thread resolved)
- A "thanks" as a standalone DM → Social
- A question in a long thread → check if directed at user specifically

### Bot Messages
Skip messages from bots/integrations unless they contain actionable items (e.g., CI failure notifications → Action Needed).

## Auto-Reply Templates

Auto-replies should match the user's tone profile. Default templates (adapted per tone):

### FYI Acknowledgment
- Professional: "Noted, thank you for the update."
- Casual: "Got it, thanks!"
- Vietnamese casual: "Noted nha, cảm ơn!"

### Social Response
- Greetings: Mirror the greeting style ("Hi!" → "Hi!", "Chào anh" → "Chào anh!")
- Thanks: React with emoji (👍) instead of text reply
- Congrats: Short acknowledgment + emoji

### Action Needed (Draft)
- Include acknowledgment + estimated response time
- "Will review shortly" / "Sẽ check sớm nha"
- Never auto-send — always queue for approval

### Urgent (Draft)
- Acknowledge urgency + indicate availability
- "Looking into this now" / "Đang check rồi"
- Never auto-send — always queue for approval
