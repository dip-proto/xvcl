// Test: VCL strings, heredocs, and templates are scanned like Fastly does


sub vcl_recv {
  // A backslash is an ordinary character in a VCL string
  set req.url = std.replaceall(req.url, "\", "/");
  set req.http.X-Home = "\" + "https://example.com/" + "home";
  // Text inside a template is Python, even when it looks like a macro call or a quote
  set req.http.X-Raw = "url(raw)";
  set req.http.X-Len = "https://example.com/" + "1";

  // In a template, // is Python's integer division
  if (std.atoi(req.http.X-N) > 50) {
    set req.http.X-Big = "1";
  }
  set req.http.X-Half = std.itoa(50); set req.http.X-Url = "https://example.com/" + "half";

  // A condition can be built from conditional pieces
  if (
    req.http.X-Release
  ) {
    set req.http.X-Picked = "1";
  }
}

sub vcl_error {
  // Heredoc delimiters may contain digits and underscores
  synthetic {EOF_1"<a href="url(home)">here</a>"EOF_1};
  set obj.http.Location = "https://example.com/" + "home";
  return(deliver);
}
