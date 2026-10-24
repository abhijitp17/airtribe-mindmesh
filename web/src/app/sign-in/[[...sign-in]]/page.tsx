import { SignIn } from "@clerk/nextjs";
import AuthFrame from "@/components/AuthFrame";

export default function SignInPage() {
  return (
    <AuthFrame title="Sign in to Mindmesh">
      {/* /claim saves a signed-out gap report if one is waiting, then goes to Today. */}
      <SignIn path="/sign-in" routing="path" signUpUrl="/sign-up" fallbackRedirectUrl="/claim" />
    </AuthFrame>
  );
}
