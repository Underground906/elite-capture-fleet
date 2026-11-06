#!/usr/bin/env bash
# Local capture of robot-blocked front ends (home connection + installed Chrome, headless). Resumable; restarts itself if killed.
cd /c/Users/under/Downloads/UI_LIBRARY_V2/elite-fleet
export ELITE_CHANNEL=chrome ELITE_RCLONE=/c/Users/under/bin/rclone.exe ELITE_MIN_FREE_MB=700 ELITE_HEAP=768 ELITE_TIMEOUT=480 PYTHONIOENCODING=utf-8
for try in 1 2 3 4 5 6 7 8 9 10; do
  echo "== start $try $(date)" >> local_blocked.log
  python -u elite_run.py $(cat local_jobs.txt) >> local_blocked.log 2>&1 && { echo FINISHED >> local_blocked.log; exit 0; }
  echo "== exited $? $(date), restarting" >> local_blocked.log; sleep 60
done
