declare var rivets: any;
declare var $: any;
declare var Vue: any;

(async () => {
    let promise = fetch("/api/links/");
    const links: Array<any> = await (await promise).json();

    let linksDict = {};
    links.forEach(link => {
        if (link.parent) {
            if (!linksDict[link.parent]) {
                linksDict[link.parent] = [];
            }

            linksDict[link.parent].push(link);
        }
    });

    const parents = Object.keys(linksDict);

    let data = [];

    parents.forEach(parent => {
        data.push({
            parent,
            links: linksDict[parent]
        });
    });

    const app = new Vue({
        el: "#broken-links-list",
        data: {
            linksDict,
            links,
            parents,
            data
        }
    });
})();
