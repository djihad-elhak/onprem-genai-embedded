"""Engineering console: a web application over the platform for the engineers of a site.

It shows the traceability state of the code base, searches the knowledge graph, runs the test-generation
agent with live progress, collects human review verdicts on generated tests and sizes GPU deployments. It runs
next to the model servers, needs no internet access, and stores its state in one SQLite file.
"""
