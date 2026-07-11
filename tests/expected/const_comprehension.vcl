// Test: List comprehensions in constants can reference other constants.
// Comprehension bodies run in their own scope and resolve free names through
// eval's globals, so constants must be visible there, not only in locals.

set req.http.X-Value-0 = "0";
set req.http.X-Value-1 = "2";
set req.http.X-Value-2 = "4";
set req.http.X-Joined = "024";
