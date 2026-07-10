// @scope: recv
// @suite: a line comment in a macro does not swallow later statements
sub test_multiline_macro_comment {
  testing.call_subroutine("vcl_recv");
  assert.equal(req.http.X-First, "both");
  assert.equal(req.http.X-Second, "both");
}
