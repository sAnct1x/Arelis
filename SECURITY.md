# Security

If you think you have found a hole, thank you. Please tell me privately.
A public issue puts a vulnerability on the front page of a local-first
program, and that helps nobody.

## How to report

GitHub's private report:

https://github.com/sAnct1x/arelis/security/advisories/new

That reaches me without publishing anything. Do not open an ordinary
issue for a security hole, and do not discuss it in a pull request until
it is fixed.

Say what you did, what you expected, and what happened. The version
helps: press **F1** in the window, or run `arelis --version`. Logs stay
on your machine. If you attach any, read them first. They may contain
your own paths or the text of your messages.

## What happens next

This is a one-person project. I will look. I may take a few days. I will
say whether I think it is a real hole, and if it is, I will fix it in a
release rather than leaving you to guess.

There is no bounty. The thanks is genuine. The budget is not.

## What counts

In scope: anything that sends your data off the machine without you
aiming it there, anything that sends mail or a text without you allowing
it, anything that bypasses the folder permissions you set, and any
secret or personal detail that has landed in this public repository.

Out of scope, because they are the program working as designed: Arelis
reading or changing a file inside a folder you granted, SmartScreen
warning on an unsigned installer, and a model giving a wrong or unwise
answer.

## Which versions

Fixes land in the latest published release. There is no separate patch
stream for older installers. Updating is how a fix reaches you. An
installed copy already asks GitHub once a day whether a newer release
exists.
