// A loading boundary lets a click commit the new URL at once (the shell then draws the screen from
// cached data) while the page's session check streams in. It renders nothing: the shell, not this
// file, owns every screen and its skeletons.
export default function Loading() {
  return null;
}
