Kalshi vs Polymarket Gap Checker

A Python tool that pulls live crypto prediction markets from Kalshi and Polymarket, pairs up markets that describe the same event, and measures the price gap between the two platforms.

What it found: Bitcoin downside markets showed a consistent 8 to 9 cent gap. The most likely cause was a difference in how the two platforms settle those contracts, so the markets were close but not the same bet.

How to run: install the requests library, then run python gap_checker.py. It prints any gap over 3 cents with both platforms’ settlement rules side by side, and saves every comparison to snapshots.csv.

Built in summer 2026 by Oliver Spiro, using AI coding tools.
