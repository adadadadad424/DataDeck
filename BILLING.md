# DataDeck Billing

Stand: 20.09.2026. Stripe-Testbilling ist im Code vorbereitet, aber noch deaktiviert.
Es wurden kein Preis, kein Stripe-Produkt, keine Datenbank und keine kostenpflichtige
Cloud-Ressource eigenständig angelegt.

## Architektur

- Streamlit authentifiziert Nutzer weiterhin über Google OIDC.
- Die interne `user_id` ist eine deterministische UUID aus OIDC-Issuer und Subject.
  E-Mail, Anzeigename, Browser-Cookie und Session-ID sind nicht der Primärschlüssel.
- PostgreSQL speichert ausschließlich Billing-Nutzer, Stripe-Zuordnungen, Abo-Zustand
  und bereits verarbeitete Stripe-Event-IDs.
- Streamlit erstellt Checkout- und Portal-Sessions serverseitig. Customer-IDs kommen
  immer aus PostgreSQL und niemals aus URL- oder Browserparametern.
- Der separate FastAPI-Dienst in `billing_service.py` nimmt Stripe-Webhooks entgegen.
  Er prüft die Signatur auf dem unveränderten Request-Body, bevor ein Event verarbeitet
  wird.
- Stripe bleibt die Zahlungsquelle der Wahrheit. Ein Success-Redirect zeigt nur
  "Bestätigung läuft" und erteilt niemals Pro-Zugriff.

## Datenmodell

Migration `billing/migrations/001_initial.sql` erzeugt:

- `billing_users`: OIDC-Identität, Beta-Override, Stripe Customer/Subscription,
  originaler Subscription-Status, Laufzeit und Sync-Zeitpunkt.
- `stripe_events`: Event-ID, Typ und Verarbeitungszeit für Idempotenz. Vollständige
  Stripe-Payloads werden nicht gespeichert.
- `schema_migrations`: einmalige, geordnete Migrationen statt Tabellenbau bei jedem
  App-Start.

Migration ausführen:

```bash
python -m billing.migrate
```

## Berechtigungen

Die einzige zentrale Entscheidung liegt in `billing/entitlements.py`:

```text
Zugriff = serverseitiger Beta-Zugang ODER Stripe-Status active/trialing
```

`cancel_at_period_end=true` entzieht den Zugriff nicht, solange Stripe den Status noch
als `active` oder `trialing` meldet. `past_due`, `unpaid`, `incomplete`, `canceled` und
`paused` gewähren ohne Beta-Override keinen Pro-Zugriff. Ein kurzer Stripe-Ausfall
löscht einen zuletzt bestätigten aktiven Zustand nicht aus der Datenbank.

Alle aktuell freigegebenen Invite-only-Tester erhalten weiterhin serverseitigen
Beta-Zugang. In diesem Sprint werden AI, PDF oder Upload-Limits nicht aggressiv gesperrt.

## Stripe-Flows

### Checkout

1. Angemeldete OIDC-Identität wird in PostgreSQL geladen oder angelegt.
2. Nur falls noch kein Customer gespeichert ist, wird ein Stripe Customer erzeugt.
3. Checkout läuft im Modus `subscription` mit genau einer konfigurierten Monthly Price.
4. `client_reference_id` und nicht sensible Metadata enthalten die interne `user_id`.
5. Ein Zehn-Minuten-Idempotency-Key begrenzt versehentliche Checkout-Doppelklicks.
6. Der Redirect gewährt keinen Zugriff; Webhook oder defensiver Sync bestätigen den Plan.

### Customer Portal

Eine Portal-Session wird nur für die Customer-ID aus dem Datensatz des eingeloggten
Nutzers erzeugt. Nach Rückkehr synchronisiert DataDeck die bekannte Subscription einmal
neu. Rechnungen, Zahlungsmethoden und Kündigungen bleiben Stripe-Aufgaben.

### Webhooks

Endpoint: `POST /stripe/webhook`

Verarbeitet werden:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.paid`
- `invoice.payment_failed`

Jede Event-ID wird in derselben Datenbanktransaktion wie die Statusänderung gespeichert.
Bei einem Fehler wird die gesamte Transaktion zurückgerollt und Stripe kann erneut
zustellen. Ein älteres Event kann keinen bereits verarbeiteten neueren Status ersetzen.
Für Subscription- und Invoice-Events wird der aktuelle Subscription-Zustand defensiv
bei Stripe abgerufen.

Logs enthalten Event-ID, Event-Typ, Ergebnis, Laufzeit und Fehlerklasse. Secrets,
Payloads, Zahlungsdaten und Rechnungsinhalte werden nicht geloggt.

## Konfiguration

Billing bleibt ohne `BILLING_ENABLED=true` vollständig aus. Benötigt werden dann:

```text
BILLING_ENABLED=true
STRIPE_MODE=test
DATABASE_URL=postgresql://...
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_PRO_MONTHLY=price_...
APP_BASE_URL=https://...
```

Secrets gehören ausschließlich in Render. Production verweigert den Start bei
fehlenden Werten, HTTP-Basis-URL, Nicht-PostgreSQL-Datenbank oder einem Test/Live-Key,
der nicht zu `STRIPE_MODE` passt. Die Price-ID wird vor Aktivierung zusätzlich im
Stripe-Testflow geprüft; ihr Modus ist nicht zuverlässig aus dem Text erkennbar.

## Deployment im Testmodus

Noch nicht ausführen, bis die manuellen Voraussetzungen unten erfüllt sind:

1. Verwaltete PostgreSQL-Datenbank mit TLS-Verbindung bereitstellen.
2. Migration einmal gegen diese Datenbank ausführen.
3. Separaten Render-Web-Service aus `Dockerfile.billing` erstellen.
4. Dort `DATABASE_URL`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
   `STRIPE_PRICE_PRO_MONTHLY`, `STRIPE_MODE=test` und `APP_BASE_URL` als Secrets setzen.
5. Im Streamlit-Service dieselben Werte außer `STRIPE_WEBHOOK_SECRET` setzen und erst
   danach `BILLING_ENABLED=true` aktivieren. Das Webhook-Secret gehört nur in den
   Webhook-Dienst.
6. In Stripe Workbench den HTTPS-Endpunkt
   `https://<billing-service>/stripe/webhook` für die oben genannten Events anlegen.
7. Das angezeigte `whsec_...` ausschließlich im Render Secret Store hinterlegen.

Die Webhook-URL muss direkt antworten und darf nicht umleiten. `GET /health` ist der
Healthcheck des Billing-Dienstes.

## Stripe-Betrieb

- Neuer Preis: Im Stripe-Testmodus unter demselben Produkt einen neuen wiederkehrenden
  Monthly Price erstellen. Bestehende Abos behalten ihren alten Price; danach nur die
  Render-Variable für neue Checkouts ändern.
- Manuelle Kündigung/Zahlungsprüfung: Im Stripe-Dashboard den Customer anhand der
  gekürzten technischen ID suchen. Keine Kartendaten nach DataDeck kopieren.
- Rechnungen und Zahlungsmethoden: ausschließlich Stripe Dashboard/Customer Portal.
- Refunds: zunächst manuell in Stripe. Ein Refund allein ändert nicht automatisch den
  Abo-Status; der Subscription-Status bleibt für den Zugriff maßgeblich.
- API-Key-Rotation: neuen eingeschränkten Stripe-Key in Render einsetzen, Dienste
  validieren, erst danach den alten Key widerrufen.
- Webhook-Secret-Rotation: neues Secret am Endpoint erzeugen, in beiden Render-Diensten
  austauschen, Testevent zustellen, altes Secret anschließend entfernen.
- Account-Löschung: vor administrativer Löschung eine aktive Subscription in Stripe
  behandeln; DataDeck löscht sie nicht stillschweigend.

## Noch manuell erforderlich

- Stripe-Konto im Testmodus verwenden.
- Produkt `DataDeck Pro` und genau einen monatlichen Test-Price erstellen; Preis legt
  ausschließlich der Betreiber fest.
- Persistente PostgreSQL- und Billing-Service-Kosten prüfen. Ohne ausdrücklich
  bestätigten kostenlosen Plan werden keine Render-Ressourcen angelegt.
- Stripe Customer Portal im Testmodus konfigurieren.
- Test-Price-ID und Secrets direkt in Render eintragen, niemals im Chat oder Repository.
- Stripe-CLI-/Workbench-Test für Erfolg, Payment Failure, Kündigung, Wiederholung und
  verspätete Events durchführen.

## Go-Live-Sperre

Live Billing bleibt gesperrt, bis Checkout, Signatur, Webhook, Persistenz, Payment
Failure, Portal, Kündigung, Duplicate Events und Render-Restart im Stripe-Testmodus
bestanden haben. Eine echte Zahlung wird nur nach ausdrücklicher Betreiberfreigabe
durchgeführt. Steuer-, Preis- und Rechtstexte sind keine technische Festlegung dieses
Dokuments.
