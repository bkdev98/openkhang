# Chrome DevTools Extraction Patterns for Google Chat

These are starting-point patterns for extracting data from the Google Chat web UI via `evaluate_script`. The DOM structure may change — if selectors stop working, use `take_snapshot` to inspect the current structure and adapt.

## Strategy

Google Chat's DOM uses dynamically generated class names that change across deployments. Instead of relying on class names, use:

1. **ARIA roles and labels** — most stable (`role="listitem"`, `aria-label`)
2. **Data attributes** — when available (`data-topic-id`, `data-member-id`)
3. **Semantic structure** — element hierarchy and tag relationships
4. **Text content matching** — as a last resort for identification

Always prefer `take_snapshot` first to discover element UIDs and current DOM structure. Use `evaluate_script` when you need structured data extraction that's hard to parse from the a11y tree.

## Common Extraction Patterns

### Find Spaces with Unread Messages (Sidebar)

The sidebar contains a list of spaces/DMs. Unread spaces typically have:
- Bold text styling on the space name
- An unread count badge (a small number or dot)
- Different font-weight compared to read spaces

Use `take_snapshot` to read the sidebar — unread indicators are usually visible in the a11y tree as text like "(3)" or as an aria-label containing "unread".

### Extract Messages from Current Space

After clicking into a space, messages are displayed in a scrollable container. Each message typically has:
- Sender name (in a heading or strong element)
- Message text (in paragraph or span elements)
- Timestamp (often in a tooltip or small text element)
- Thread container (if threaded)

Use `evaluate_script` to extract structured message data:

```javascript
// Example: extract visible messages — adapt selectors as needed
() => {
  // Find message containers — look for elements with message-like structure
  // The actual selectors need to be discovered from take_snapshot output
  const messages = [];

  // Strategy: find elements that contain sender + text + time pattern
  // Google Chat typically renders messages in a list with role="listitem"
  // or in containers with specific data attributes

  // Return what we find for the skill to process
  return {
    messages: messages,
    note: "Selectors should be adapted based on current DOM structure from take_snapshot"
  };
}
```

### Identify User's Own Messages

To filter out the user's own messages (for tone learning or scan filtering):
- Own messages are typically right-aligned or have a different background color
- The sender name may match the account name from state file
- Some implementations mark own messages with a specific CSS class or data attribute

### Find Reply Input

The message input is typically:
- A contenteditable div or textarea at the bottom of the chat view
- Has aria-label like "Type a message" or "Nhập tin nhắn"
- Is the last focusable input-like element in the chat area

Use `take_snapshot` → find the element with message-input-like aria-label → use its UID to `click` and `fill`.

### Thread Navigation

Threads in Google Chat appear as:
- A "Reply" button or link on each message
- Clicking opens a thread panel (usually on the right side)
- The thread panel has its own message list and reply input

To reply in a thread:
1. `take_snapshot` → find the specific message
2. `click` on the reply/thread indicator
3. Wait for thread panel to load
4. `take_snapshot` again → find the thread reply input
5. `fill` + `press_key` Enter

## Tips for Reliability

1. **Always snapshot before acting** — DOM may have changed since last interaction
2. **Use `wait_for` after navigation** — Google Chat loads content dynamically
3. **Check for loading states** — spinners, skeleton screens indicate content isn't ready
4. **Scroll if needed** — older messages may require scrolling up; unread badge spaces may be below the fold in sidebar
5. **Handle popups/dialogs** — Google Chat may show notifications or update prompts
