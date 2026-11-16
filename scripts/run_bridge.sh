#!/bin/bash
cd ~/munder-difflin
exec expect -c "
spawn claude --model claude-opus-5
expect \"Quick safety check\"
send \"y\r\"
expect \"❯\"
interact
"
