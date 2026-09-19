#!/bin/zsh
cd "$(dirname "$0")" || exit 1
echo "DataDeck Gemini-Key einrichten"
echo
echo "Fuege jetzt deinen Gemini API-Key ein und druecke Enter."
echo "Beim Einfuegen wird nichts angezeigt. Das ist normal."
printf "Gemini API-Key: "
stty -echo
IFS= read GEMINI_KEY
stty echo
echo

if [ -z "$GEMINI_KEY" ]; then
  echo "Kein Key eingegeben. Nichts gespeichert."
  exit 1
fi

printf "GEMINI_API_KEY=%s\n" "$GEMINI_KEY" > .env
echo "Gespeichert. Du kannst dieses Fenster jetzt schliessen."
