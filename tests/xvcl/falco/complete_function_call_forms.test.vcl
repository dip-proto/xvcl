// @scope: recv
// @suite: every call returns the right value and leaves no bridge header behind
sub test_results {
  set req.url = "/api/users";
  set req.http.X-Choice = "large";
  testing.call_subroutine("vcl_recv");
  assert.equal(req.http.X-Lower, "abc");
  assert.equal(req.http.X-Api, "yes");
  assert.equal(req.http.X-Pair, "one|two");
  assert.equal(req.http.X-Total, "13");
  assert.equal(req.http.X-Double, "42");
  assert.equal(req.http.X-Size, "large");
  assert.is_notset(req.http.X-Func-sign-msg);
  assert.is_notset(req.http.X-Func-sign-key);
  assert.is_notset(req.http.X-Func-sign-Return);
  assert.is_notset(req.http.X-Func-split_pair-Return0);
}

// @scope: recv
// @suite: the last return runs when nothing earlier matched
sub test_fallbacks {
  set req.url = "/home";
  set req.http.X-Choice = "medium";
  testing.call_subroutine("vcl_recv");
  assert.equal(req.http.X-Api, "no");
  assert.equal(req.http.X-Size, "none");
}
