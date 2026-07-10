// Test: Parentheses in comments and strings do not join unrelated lines (
/* A multiline comment also contains (
   without a matching close parenthesis. */

sub vcl_recv {
    set req.http.X-Open = "(";
    set req.http.X-Close = ")";
}
