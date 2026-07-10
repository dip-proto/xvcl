// @scope: recv
// @suite: an early return skips the rest of the generated function
sub test_early_return {
  set req.http.X-Func-choose-value = "first";
  testing.call_subroutine("choose");
  assert.equal(req.http.X-Func-choose-Return, "value literal");
  assert.is_notset(req.http.value);
}

// @scope: recv
// @suite: parameter substitution leaves VCL long strings unchanged
sub test_long_string {
  set req.http.X-Func-choose-value = "long";
  testing.call_subroutine("choose");
  assert.equal(req.http.X-Func-choose-Return, "value literal");
  assert.is_notset(req.http.value);
}

// @scope: recv
// @suite: the final return writes its value
sub test_final_return {
  set req.http.X-Func-choose-value = "left,right";
  testing.call_subroutine("choose");
  assert.equal(req.http.X-Func-choose-Return, "left;right");
  assert.equal(req.http.value, "left,right");
}

// @scope: recv
// @suite: commas in tuple return expressions are parsed correctly
sub test_tuple_return {
  set req.http.X-Func-split-value = "left,right";
  testing.call_subroutine("split");
  assert.equal(req.http.X-Func-split-Return0, "left;right");
  assert.equal(req.http.X-Func-split-Return1, "value literal");
}

// @scope: recv
// @suite: multiline function calls in return expressions are transformed
sub test_multiline_return {
  set req.http.X-Func-normalize-value = "left,right";
  testing.call_subroutine("normalize");
  assert.equal(req.http.X-Func-normalize-Return, "left;right");
}

// @scope: recv
// @suite: every function call in a multiline statement macro is transformed
sub test_multiline_macro_function_calls {
  testing.call_subroutine("vcl_recv");
  assert.equal(req.http.X-One, "value literal");
  assert.equal(req.http.X-Two, "left;right");
}

// @scope: recv
// @suite: every XVCL call on one physical line is transformed
sub test_same_line_function_calls {
  testing.call_subroutine("vcl_recv");
  assert.equal(req.http.X-Inline-One, "value literal");
  assert.equal(req.http.X-Inline-Two, "left;right");
}
