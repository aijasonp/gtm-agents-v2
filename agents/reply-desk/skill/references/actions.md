# Actions per class

CRM writes and sends wait for human approval. Sequence stops run at once (a stop only reduces contact) and are logged in the approval queue. Opt-outs and bounces go on the shared do-not-contact list immediately, which cancels pending sends to that person and blocks every other agent.

| Class | Local (immediate) | Queued for approval | Outcome logged for learning |
| --- | --- | --- | --- |
| bounce | email marked invalid | sequence stop; task to fix the address | none |
| unsubscribe | do_not_contact = true | sequence stop; CRM opt-out field | reply_negative |
| out_of_office | ooo_until = return date | none (sequence keeps going after the date) | none |
| referral | referred contact added; left_company if they left | sequence stop; new CRM contact; drafted intro as a send task. Name but no email: Enrichment lookup plus a task | none |
| positive | none | sequence stop; owner task due in 2 business hours; drafted reply as a send task; Slack alert | reply_positive, or meeting when a day and time is proposed |
| objection | none | drafted answer as a send task; sequence stop when the answer is "no need" | reply_negative, or bad_fit for "not a fit" |
| not_now | none | sequence stop; task due on the parsed date | none |
| question | none | drafted answer when approved facts cover it, else a task | none |
| neutral | listed for review | none | none |

Drafted replies must pass the Copy QA Gate. A draft that fails becomes a task to write the reply by hand.

## Owner

Contact owner, then account owner, then the open deal's owner, then the owner on the outbound or lead draft that started the thread, then the lead's owner, then the default owner in config.
