'use strict';
// Official v1.28 persistentAtom key; no token or password is written here.
localStorage.setItem('endpointURL', location.origin + '/graphql');
location.replace('/index.html' + location.hash);
