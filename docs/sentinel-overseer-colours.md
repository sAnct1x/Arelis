# Reading the Overseer: colours and counts

## Rose means a real threat

In the Sentinels window, rose (bright pink-red) is only used for a real
threat: a Warden engaging a blocked connection, or a threat marker the hive
reports. Those same events raise the **Threats** count.

Everything routine takes the colour of the caste doing it:

- A Warden's regular socket patrol shows violet packets, the Warden colour.
- Sources a research mission brings back show light blue, the Harvester colour.

So if Threats reads 0, you should see no rose in the scene.

## What Warrants counts

Hover the **Warrants** block in the status strip to see what it means:
evidence receipts in memory. Every
caste writes one each time it does a job, such as a patrol scan, a file
check, or a page it read. When Sentinel starts, it loads up to 120 receipts
from earlier runs, so the count never starts at 0 and climbs while the
swarm patrols. It is not a count of threats. Sentinel keeps up to 1000 in
memory.

## Labels

- The mission picker reads **Mode:** followed by the mission type.
- The Swarm list groups read Caste, Task and Ring.
- Search and filter hints are easier to read.
- Focus and Fit swarm move the camera without leaving a status line under
  Dispatch.
