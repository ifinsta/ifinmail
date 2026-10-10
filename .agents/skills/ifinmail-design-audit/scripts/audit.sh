#!/usr/bin/env bash
# ifinmail design audit: flags common departures from the redesign.
# Usage: audit.sh [path ...]   (default: frontend/templates and frontend/static/css)
# Exit status: 0 when clean, 1 when anything was reported.
#
# Exempt from the colour/inline-style checks:
#   - frontend/static/css/ifinmail-variables.css (the token source)
#   - frontend/static/error-pages/*  (self-contained nginx fallbacks)
#   - password_reset_email.html, email_verify.html (mail clients need inline literals)

set -u
export LC_ALL=C.UTF-8

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT" || exit 2

if [ "$#" -gt 0 ]; then
  TARGETS=("$@")
else
  TARGETS=(frontend/templates frontend/static/css)
fi

mapfile -t FILES < <(find "${TARGETS[@]}" -type f \( -name '*.html' -o -name '*.css' \) 2>/dev/null | sort)

# Findings are counted through a file because reports are emitted from pipeline subshells.
COUNT_FILE="$(mktemp)"
trap 'rm -f "$COUNT_FILE"' EXIT
report() { # rule, file:line:text
  echo x >> "$COUNT_FILE"
  printf '%-18s %s\n' "[$1]" "$2" | cut -c1-200
}

is_exempt_colour() {
  case "$1" in
    *ifinmail-variables.css|*static/error-pages/*|*password_reset_email.html|*email_verify.html) return 0 ;;
  esac
  return 1
}

for f in "${FILES[@]}"; do
  case "$f" in *.html) kind=html ;; *.css) kind=css ;; esac
  exempt=0; is_exempt_colour "$f" && exempt=1

  if [ "$exempt" -eq 0 ]; then
    # Literal colours (skip lines that define or reference variables and fallbacks like var(--x, #fff))
    grep -nE '#[0-9a-fA-F]{3,8}\b|rgba?\(' "$f" | grep -vE 'var\(--[a-z0-9-]+, *#|rgba?\(var\(|theme-color' | grep -vE '^\s*[0-9]+:\s*(/\*|\*|//|\{#)' \
      | grep -vE '&#[0-9]+;' | while IFS= read -r l; do report "hardcoded-colour" "$f:$l"; done
    # Gradients
    grep -nE 'linear-gradient|radial-gradient|conic-gradient' "$f" | while IFS= read -r l; do report "gradient" "$f:$l"; done
  fi

  if [ "$kind" = html ] && [ "$exempt" -eq 0 ]; then
    # Inline styles (allow computed width/height/--vars only)
    grep -nE 'style="' "$f" | grep -vE 'style="[^"]*(\{\{|\{%)' | while IFS= read -r l; do report "inline-style" "$f:$l"; done
    # Clickable non-controls
    grep -nE '<(div|span|li|p)[^>]*(onclick=|role="button")' "$f" | while IFS= read -r l; do report "fake-button" "$f:$l"; done
    # Images without alt
    grep -nE '<img\b' "$f" | grep -vE '\balt=' | while IFS= read -r l; do report "img-no-alt" "$f:$l"; done
    # Inputs a label cannot target
    grep -nE '<input\b' "$f" | grep -vE '\bid=|type="(hidden|submit|checkbox|radio)"' | while IFS= read -r l; do report "input-no-id" "$f:$l"; done
    # Headings, buttons, table headers with untranslated literal text
    grep -nE '<(h[1-3]|th|button)\b[^>]*>[[:space:]]*[A-Za-z][A-Za-z ]+<' "$f" | while IFS= read -r l; do report "untranslated" "$f:$l"; done
    # Emoji / pictographs
    grep -nP '[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}]' "$f" | while IFS= read -r l; do report "emoji" "$f:$l"; done
    # More than one primary button
    n=$(grep -o 'ifinmail-btn--primary' "$f" | wc -l)
    # Informational only: several primaries are fine when they are separate states, dialogs or repeated CTAs.
    if [ "$n" -gt 1 ]; then printf '%-18s %s\n' "[note]" "$f: $n primary buttons (confirm they are separate states or dialogs)"; fi
  fi

  if [ "$kind" = css ] && [ "$exempt" -eq 0 ]; then
    # Shadows other than none/tokens (menus, dialogs, landing preview are the allowed exceptions; review each hit)
    grep -nE 'box-shadow:' "$f" | grep -vE 'box-shadow:\s*(none|var\(--ifinmail-shadow)' | grep -vE 'focus|inset 0 0 0|box-shadow: 0 0 0 ' \
      | while IFS= read -r l; do report "shadow" "$f:$l"; done
    # Tiny type
    grep -nE 'font-size:\s*(([0-9]|10|11)(\.[0-9]+)?px|0?\.(5|6)[0-9]*rem|0\.6875rem)' "$f" | grep -vE 'overline|caption' \
      | while IFS= read -r l; do report "small-type" "$f:$l"; done
    # Uppercase outside overlines, pills and badges
    # (allowed when the same rule sets overline tracking, 0.06-0.08em, or its selector names an overline, badge or pill)
    awk '/\{/ {blk=""; sel=$0} {blk=blk"\n"$0} /text-transform:[ ]*uppercase/ {ln=NR; txt=$0; want=1} /\}/ { if (want && blk !~ /letter-spacing:[ ]*0\.0[6-8]/ && sel !~ /overline|badge|pill|uppercase/) print ln":"txt; want=0 }' "$f" \
      | while IFS= read -r l; do report "uppercase" "$f:$l"; done
  fi
done

if [ ! -s "$COUNT_FILE" ]; then
  echo "ifinmail design audit: clean (${#FILES[@]} files checked)"
  exit 0
fi
echo
echo "ifinmail design audit: $(wc -l < "$COUNT_FILE") finding(s) above. Fix them or note why each is a legitimate exception."
exit 1
