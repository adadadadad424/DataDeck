# Pricing Architecture (ohne finale Preise)

## Basismodell

- Ein Basisplan enthält eine definierte Zahl von Arbeitsplätzen und Mandanten.
- Weitere Arbeitsplätze und weitere Mandanten sind getrennte Add-ons.
- Analyse-, Export- und KI-Kontingente werden serverseitig als Entitlements modelliert, nicht nur in der Oberfläche.
- Bei kurzzeitigen Stripe-Störungen bleibt der zuletzt bestätigte Subscription-Status erhalten. Eine feste Grace-Period ist noch nicht produktseitig definiert.

## Produktgrenzen

`OWNER` verwaltet Workspace, Billing und Branding. `PARTNER` darf Berichte freigeben und Aktivitäten sehen. `CONSULTANT` arbeitet an Mandanten, Analysen und Exporten. `VIEWER` besitzt reinen Lesezugriff. Finale Preise und Mengen werden erst nach Beta-Nutzungsdaten festgelegt.
