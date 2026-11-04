# Calls

`proxenos call` places a phone call for you and waits on hold so you don't have to. When a person picks up, it tells them it's an automated assistant calling for you, then rings your phone; you press 1 and you're talking to them. It can also ask for a few things itself, such as an itemized bill or a reference number, when you don't come to the phone or when the call sheet says so.

It's for the calls that are mostly waiting: a billing office, an insurer, a pharmacy. You start every call, on the page's Calls view or with `proxenos call start NAME`.

## What it says, and what it never does

- **It says what it is.** To the first person who answers it says: "Hi, I'm an automated assistant calling for <your name>, and this call is transcribed." It never says it's you, and it has no voice of yours: it speaks in one of Twilio's voices. The other side has to know, both because they have to check they're talking to the patient or someone the patient allowed, and because some states, New Hampshire among them, need everyone's consent to a call being recorded or listened to by a machine. Transcribed is all it is: Twilio's speech recognition hears the call to write it down, and nothing records it (the call is placed with `Record` false, and nothing Proxenos tells Twilio during it records).
- **It checks the number first.** A number on a sheet can come from a scam: an email saying a bill is overdue, with a number to call. Before each call, and when `proxenos call list` runs, Proxenos looks for the number in your records. If it's in just one message someone sent you, and in nothing you've sent, written down or put in a calendar, nor in any other mail or chat, the sheet says so on the page and the call doesn't start: check the number on the organization's own website or a bill, then press **Call anyway** (or run `proxenos call start NAME --anyway`). A number found nowhere in your records isn't doubted, since it came from somewhere else, such as a bill.
- **It never agrees to pay.** Not a payment, a settlement or a payment plan. Code checks every reply before it's said and replaces one that would agree. It asks them to note an offer on the account and brings it back to you.
- **It only knows what the sheet tells it.** It may give them the facts the sheet lists (your name, a date of birth, an account number) and nothing else, so it has no Social Security, card or bank number to give. A reply with a number that isn't on the sheet, and isn't one they just said, isn't said.
- **It puts you through when it should.** When they ask for something it doesn't have, ask for a Social Security, card or bank number, want the patient, or won't talk to an assistant, it rings you. It does the same if the model doesn't answer in time.
- **On hold it says nothing.** It tells the hold's own messages ("your call is important to us") and a message it has heard before from a person picking up ("thanks for holding, this is Dana"). When it can't tell, the model decides.

## A call sheet

One file per call in the vault, `clones/calls/<name>.md`. The page lists them. For example:

```markdown
---
title: "Clinic billing about the March visit"
to: "Example Clinic billing"
number: "+16035550142"
digits: "ww1ww2"
about: "the bills from a clinic visit on March 3"
asks: ["A hold on the account while it's reviewed", "An itemized bill", "The financial assistance application", "A reference number for this call"]
facts: {"name": "Sam Lee", "date of birth": "01/02/1990", "account": "A-778812"}
talk: false
---

Notes for you: hours, what happened last time.
```

- **number:** the whole number, with the country code.
- **digits:** the phone menu's keys, pressed once the call connects. `w` waits half a second. Leave it empty until you know the menu; after the first call, put in the keys that reach a person.
- **about:** said to whoever answers: "I'm calling about …".
- **asks:** what to ask for, in order.
- **facts:** what it may tell them, by name. On the page you see only the names, not the values.
- **talk:** false (the default) rings you as soon as a person answers, and it asks for things itself only if you don't pick up. true has it ask for everything itself and ring you only when it needs you.

After each call, `clones/calls/<name>/<started>.json` keeps the transcript, the person's name, the reference number, what they offered, and what came of each ask, as the model read it. While a call goes, `<name>/live.json` says where it is, for the page.

## Setting it up

It needs a phone service that a program can dial through. Proxenos uses your own [Twilio](https://www.twilio.com) account, so the calls and the bill are yours. Only you can open the account and pay for it; Proxenos never does either.

1. **Open a Twilio account**, then upgrade it with a little credit. A trial account can only call numbers you've verified, so it can't call a billing office.
2. **Buy a phone number** in Twilio's console (Phone Numbers, Buy a number), one that can make voice calls. It's what rings you. A US number costs about a dollar a month, and calls about a cent or two a minute. Twilio's speech recognition, which hears the call, is charged by the minute too; a long hold costs more. Check Twilio's pricing page.
3. **Verify your own phone number** as a caller ID (Phone Numbers, Verified Caller IDs). Twilio calls it once with a code. Then the office sees your number and can call you back. Without it, they see the Twilio number.
4. **Put the account's SID and auth token** (on the console's front page) in the page's Settings, which keeps them in the Keychain, or in `.env` as `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`. Never paste them anywhere else.
5. **Set the rest** in `.env` or the settings file:

   ```bash
   PROXENOS_TWILIO_NUMBER=+16035550199   # the number you bought: it rings you
   PROXENOS_CALLER_ID=+16035550123       # your own number, verified in step 3 (optional)
   PROXENOS_PHONE=+16035550123           # your phone, which it rings
   PROXENOS_CALLS_URL=https://your-mac.your-tailnet.ts.net:10000
   ```

   `PROXENOS_NAME` (set at first run) is the name it says.
6. **Let Twilio reach this Mac.** Twilio asks your Mac what to do next all through a call, so the call server needs a public address. [Tailscale Funnel](https://tailscale.com/kb/1223/funnel) gives it one without opening anything else. With Tailscale set up (`proxenos phone`), run:

   ```bash
   tailscale funnel --bg --https=10000 http://127.0.0.1:4748
   ```

   The first time, Tailscale may ask you to allow Funnel for your tailnet in its admin console. Port 10000 is used because 443 and 8443 already carry the page and Alexandria over Serve, privately. Funnel opens only port 10000. Nothing listens behind it except during a call, and then only to requests Twilio signed with your auth token, at a path with that call's own random token in it: every POST, which is all Twilio sends, is checked against its `X-Twilio-Signature` before anything else (`callserver._Handler.do_POST`, with `twilio.signed`), and the only GET it answers is the call's own `ping`, which says "ok" to the check that Twilio can reach the Mac. Set `PROXENOS_CALLS_URL` to the address it prints, with `:10000`.
7. **Try it on a number you own** first, such as a friend's phone or a second line. Make a sheet with `talk: false` and press Call. Before dialing, `proxenos call start` checks that Twilio can reach the Mac and says so if it can't. If it says so while Funnel is on, `proxenos call start NAME --no-check` skips the check.

The model on the call is `PROXENOS_CALL_MODEL` if it's set, else `PROXENOS_MODEL`. A local model is loaded when the call starts, and other model work waits while a call goes, so a turn takes about a second. Twilio gives each turn 15 seconds. If the model is still thinking after 8, the assistant says "one moment"; if it still has nothing after 16, it rings you.

## Privacy

The call's audio goes through Twilio, which hears it to transcribe it and to speak the assistant's words. What the other side says goes to the call's model to decide the next turn, and after the call to say what came of it. With a local model it stays on your Mac. With the Anthropic API it goes to Anthropic. The transcript, notes and outcome are kept in the vault, readable only by you.
