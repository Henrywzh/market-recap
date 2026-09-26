"""Recorded history that cannot be downloaded later.

The nightly build rebuilds every artifact from its publishers, so it keeps no
state beyond the MONITOR ledger. Two things do not work that way: free option
chains carry no history at all, and the intraday repricing of rate futures and
event markets is gone once the day ends. This package records both, append
only, into a directory the scheduled job commits to the ``snapshots`` branch
(``docs/information_architecture.md``, "Collections to start early").

A snapshot never feeds the page directly. Every row carries its fetch time
and source, and a missing answer is recorded as missing.
"""
