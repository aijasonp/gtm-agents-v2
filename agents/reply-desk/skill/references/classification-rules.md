# Classification rules

Replies are cleaned first: everything after a quoted-history marker ("On ... wrote:", "From:", "Original Message", lines starting with ">"), mobile footers ("Sent from my phone") and the sign-off line is removed. Rules run on the cleaned text, except bounce and out of office, which also read the raw text.

| Order | Class | Fires on | Confidence |
| --- | --- | --- | --- |
| 1 | bounce | sender is a mail system (mailer-daemon, postmaster), or "undeliverable", "address not found", "delivery failed", "recipient rejected", 550-554 codes | 0.97 |
| 2 | unsubscribe | "remove me", "unsubscribe" as the message, "stop emailing", "do not contact", "opt out", "delete my data", GDPR, CCPA or CASL language. Footer links ("click here to unsubscribe") are ignored | 0.97 |
| 3 | out_of_office | "out of office", "on leave", "automatic reply", "limited email" | 0.92 |
| 4 | referral | "not the right person", "no longer with", "you should talk to", "I've copied", "the best person is" | 0.85 |
| 5 | not_now | "not right now", "next quarter", "Q2", "in March", "in 3 months", "after the new year", "budget freeze" | 0.82 |
| 6 | objection | competitor ("already use", "under contract"), price ("too expensive", "no budget"), timing ("bad timing", "not a priority"), no need ("not interested", "not a fit", "no thanks") | 0.80 |
| 7 | positive | "let's talk", "happy to chat", "send times", "sounds interesting", "interested" (not "not interested"), "yes", a proposed day and time | 0.85 |
| 8 | question | a question mark or question opening | 0.55 |
| 9 | neutral | nothing matched | 0.40 |

Interest beats a competitor or timing objection in the same reply ("we already use X but happy to look" is interested).

## Dates

- Out of office: "back on Monday, November 3", "until Nov 3rd", "returning 11/3". No date: 7 days.
- Not now: next quarter is the first day of the next quarter; next year is January 1; "in March" is March 1; "Q2" is April 1 (next one); "in 3 months" is 90 days. No date: 90 days.

## Model refinement

Only for question and neutral (confidence under 0.6). The model may move the reply to another class, including opt-out. It may never move a reply out of bounce or opt-out.
