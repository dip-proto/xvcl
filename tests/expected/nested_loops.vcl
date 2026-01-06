// Test: Nested loops

// Two levels of nesting
backend us_prod {
    .host = "prod.us.example.com";
}
backend us_staging {
    .host = "staging.us.example.com";
}
backend eu_prod {
    .host = "prod.eu.example.com";
}
backend eu_staging {
    .host = "staging.eu.example.com";
}

// Three levels of nesting
set req.http.X-us-prod-a = "active";
set req.http.X-us-prod-b = "active";
set req.http.X-us-staging-a = "active";
set req.http.X-us-staging-b = "active";
set req.http.X-eu-prod-a = "active";
set req.http.X-eu-prod-b = "active";
set req.http.X-eu-staging-a = "active";
set req.http.X-eu-staging-b = "active";

// Nested with range
set req.http.X-Cell-0-0 = "0";
set req.http.X-Cell-0-1 = "1";
set req.http.X-Cell-1-0 = "2";
set req.http.X-Cell-1-1 = "3";

// Nested with conditionals inside
set req.http.X-Region-us = "enabled";
set req.http.X-Region-eu = "enabled";
