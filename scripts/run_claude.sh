#!/bin/bash
cd ~/munder-difflin
expect -c "
spawn claude --model claude-opus-5
expect \"Quick safety check\"
send \"y\r\"
expect \"❯\"
interact
"
