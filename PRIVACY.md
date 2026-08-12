# Privacy notice

The public dashboard does not require an account. Saved-role identifiers remain only in the browser’s `localStorage`; they are never uploaded or linked to an email address.

Email subscription stores only the normalised email address, subscription status, creation/confirmation/unsubscribe times, token hashes, the last digest marker and minimal delivery-failure state. Supabase hosts this data; Resend receives the address and email content solely to deliver confirmation and digest messages. Addresses are not sold, shared for advertising or used to build profiles. Emails contain no tracking pixels.

Double opt-in is required. Confirmation links expire. Every digest includes one-click unsubscribe and `List-Unsubscribe` headers. Unsubscribing changes the record immediately; repeated requests are safe. To request complete deletion rather than suppression, contact the repository maintainer through the private address configured in the deployed project’s security contact (do not publish a private personal address in this repository).

The deployed pruning function removes pending unconfirmed subscriptions after 30 days and expired operational rate-limit rows; the digest invokes it before selecting recipients. Bounced and unsubscribed records require an operator retention/deletion policy appropriate to the deployment, and complete deletion requests remain a manual maintainer action. Repository role data contains no subscriber information.
