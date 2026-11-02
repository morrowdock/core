import re, subprocess, sys
base=sys.argv[1]
commits=subprocess.check_output(['git','rev-list',base+'..HEAD'],text=True).splitlines()
for commit in commits:
 body=subprocess.check_output(['git','show','-s','--format=%B',commit],text=True)
 if not re.search(r'^Signed-off-by: .+ <[^<>\s]+@[^<>\s]+>$',body,re.M):
  raise SystemExit('Missing DCO sign-off: '+commit)
