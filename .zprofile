
# Put ~/.local/bin first so ollama (pipx install) wins over /usr/local/bin/ollama symlink
export PATH="$HOME/.local/bin:$PATH"

# Setting PATH for Python 3.13
# The original version is saved in .zprofile.pysave
PATH="/Library/Frameworks/Python.framework/Versions/3.13/bin:${PATH}"
export PATH

# Setting PATH for Python 3.14
# The original version is saved in .zprofile.pysave
PATH="/Library/Frameworks/Python.framework/Versions/3.14/bin:${PATH}"
export PATH

##
# Your previous /Users/aryanagarwal/.zprofile file was backed up as /Users/aryanagarwal/.zprofile.macports-saved_2026-05-28_at_01:44:07
##

# MacPorts Installer addition on 2026-05-28_at_01:44:07: adding an appropriate PATH variable for use with MacPorts.
export PATH="/opt/local/bin:/opt/local/sbin:$PATH"
# Finished adapting your PATH environment variable for use with MacPorts.

eval "$(/opt/homebrew/bin/brew shellenv)"
eval "$(/opt/homebrew/bin/brew shellenv)"

# >>> OpenAlice CLI >>>
export PATH='/Users/aryanagarwal/.openalice/bin':$PATH
# <<< OpenAlice CLI <<<

# QODER_DISPATCHER_PATH v1
path=("$HOME/.qoder/entry" ${path:#"$HOME/.qoder/entry"})
export PATH
# END QODER_DISPATCHER_PATH v1
