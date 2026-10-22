# Comprehension Bench

Comprehension Bench helps a team run a small, honest comparison of how people understand different explanations or work artifacts. It retains task prompts, participant answers, timestamps, manual rubric scores, and missing data instead of collapsing them into an impressive-looking single score.

The demo study asks readers to trace a document preview request, identify an authorization failure boundary, and choose a safe place for a change. Participants are assigned an artifact condition such as ordinary docs or an interactive explanation. A reviewer scores each answer against explicit rubric items. The summary distinguishes unsubmitted tasks, submitted but unscored answers, and scored answers.

The first release is a local CLI and portable JSON/CSV exports. It supports pseudonymous participant IDs, first attempts and labeled practice/repeats, and descriptive summaries with visible denominators. Repeated exposure to the same task can teach the answer, so the primary comparison uses first attempts only by default and marks cross-condition exposure.

It does not infer comprehension from reading time, auto-grade free text, randomize a study, establish causality, or produce statistical significance claims. Small demonstrations remain demonstrations.

Validate whether a researcher can prepare tasks, retain exact scoring rationale, and audit a summary without hand-reconstructing a spreadsheet. Any later claim that one explanation improves understanding requires a study design and evidence beyond this tool's fixture data.
