import { Landing } from "@/components/landing/Landing";
import { SKIP_LANDING_SCRIPT } from "@/lib/entry";

/**
 * The landing page: the name, what it means, a few live counts from the vault, and the way in.
 * The app itself is another route (/app), so none of it loads here.
 */
export default function LandingPage() {
  return (
    <>
      {/* Runs before the landing paints: coming back in the same session goes straight to the app. */}
      <script dangerouslySetInnerHTML={{ __html: SKIP_LANDING_SCRIPT }} />
      <Landing />
    </>
  );
}
