import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

export default async function Home() {
  const cookieStore = await cookies();
  const cookieName = process.env.NODE_ENV === "production" ? "__Host-token" : "token";
  const hasSession = cookieStore.has(cookieName);

  if (hasSession) {
    redirect("/search");
  }
  return (
    <div className="flex min-h-full flex-1 flex-col items-center justify-center bg-zinc-50 p-8 font-sans dark:bg-black">
      <main className="w-full max-w-lg rounded-xl border border-zinc-200 bg-white p-10 dark:border-zinc-800 dark:bg-zinc-950">
        <h1 className="text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
          Business RAG Platform
        </h1>
        <p className="mt-3 text-lg leading-8 text-zinc-600 dark:text-zinc-400">
          Upload documents per business, then query with RAG. Start by signing in.
        </p>
        <div className="mt-8">
          <Link
            href="/auth"
            className="inline-flex rounded-md bg-zinc-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            Sign in
          </Link>
        </div>
      </main>
    </div>
  );
}
